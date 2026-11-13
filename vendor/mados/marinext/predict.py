# -*- coding: utf-8 -*-
'''
Description: predict.py applies MariNeXt to a new Sentinel-2 image (outside
             the MADOS splits) and writes a georeferenced class map and an
             oil spill mask. The input must be ACOLITE L2R rhorc reflectance
             (11 bands), the same product the model was trained on.
'''

import os
import re
import sys
import argparse
import numpy as np
from glob import glob
from xml.sax.saxutils import quoteattr
from tqdm import tqdm
from os.path import dirname as up

import rasterio
from rasterio.enums import Resampling

import torch
from torch.nn import functional as F

sys.path.append(up(os.path.abspath(__file__)))
from marinext_wrapper import MariNext

sys.path.append(os.path.join(up(up(os.path.abspath(__file__))), 'utils'))
from dataset import bands_mean, bands_std
from assets import labels, mados_cat_mapping, bool_flag

root_path = up(up(os.path.abspath(__file__)))

TILE = 240                                   # patch size used during training
OIL_SPILL = mados_cat_mapping['Oil Spill']   # 6, same 1-based ids as the MADOS masks

# Hex values of the colour names in assets.mados_color_mapping, in class order 1..15
CLASS_COLORS = ['#ff0000', '#008000', '#32cd32', '#a52a2a', '#ffa500', '#d8bfd8', '#000080', '#ffd700',
                '#800080', '#bdb76b', '#00ced1', '#ffe4c4', '#696969', '#ff69b4', '#ffff00']

# QGIS raster style (paletted). QGIS applies <name>.qml automatically when <name>.tif is added.
QML_TEMPLATE = '''<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28.0" styleCategories="AllStyleCategories">
  <pipe>
    <rasterrenderer type="paletted" band="1" opacity="1" alphaBand="-1" nodataColor="">
      <rasterTransparency/>
      <colorPalette>
%s
      </colorPalette>
    </rasterrenderer>
    <brightnesscontrast brightness="0" contrast="0" gamma="1"/>
    <huesaturation saturation="0" colorizeOn="0" grayscaleMode="0" colorizeRed="255" colorizeGreen="128" colorizeBlue="128" colorizeStrength="100"/>
    <rasterresampler maxOversampling="2"/>
  </pipe>
  <blendMode>0</blendMode>
</qgis>
'''

###############################################################
# Input                                                       #
###############################################################
def get_wavelength(path):
    return int(re.search(r'rhorc_(\d+)', os.path.basename(path)).group(1))

def is_used_band(path):
    # MADOS uses B1-B8, B8A, B11, B12 (B9 ~945 nm and B10 ~1375 nm are excluded)
    wl = get_wavelength(path)
    return not (930 <= wl <= 960 or 1360 <= wl <= 1390)

def load_image(input_path):
    '''Returns an (11, H, W) float32 array and the rasterio profile of its grid.'''
    if not os.path.exists(input_path):
        raise FileNotFoundError('Input folder/file not found: %s' % input_path)

    if os.path.isdir(input_path):
        # Folder with one ACOLITE rhorc GeoTIFF per band (e.g. *_L2R_rhorc_492.tif)
        band_files = glob(os.path.join(input_path, '**', '*rhorc_*.tif'), recursive=True)
        band_files = sorted([f for f in band_files if is_used_band(f)], key=get_wavelength)
        if len(band_files) != 11:
            raise ValueError('Expected 11 rhorc bands in %s, found %d: %s'
                             % (input_path, len(band_files), [os.path.basename(f) for f in band_files]))

        # Reference grid = band with the most pixels (a 10 m band)
        sizes = []
        for f in band_files:
            with rasterio.open(f) as src:
                sizes.append(src.height * src.width)
        with rasterio.open(band_files[int(np.argmax(sizes))]) as src:
            profile = src.profile.copy()
            height, width = src.height, src.width

        # Upsample coarser bands to 10 m with nearest, as in dataset.py
        bands = []
        for f in band_files:
            with rasterio.open(f) as src:
                bands.append(src.read(1, out_shape=(height, width),
                                      resampling=Resampling.nearest).astype('float32'))
        image = np.stack(bands)
    else:
        # Single GeoTIFF with the 11 bands already stacked in wavelength order
        with rasterio.open(input_path) as src:
            image = src.read().astype('float32')
            profile = src.profile.copy()
        if image.shape[0] != 11:
            raise ValueError('Expected an 11-band GeoTIFF, found %d bands' % image.shape[0])

    return image, profile

def preprocess(image):
    '''Impute NaNs with the band mean and standardize, as in dataset.py.'''
    nodata = ~np.isfinite(image).any(axis=0)
    for b in range(image.shape[0]):
        invalid = ~np.isfinite(image[b])
        image[b][invalid] = bands_mean[b]
    image = (image - bands_mean.reshape(-1, 1, 1)) / bands_std.reshape(-1, 1, 1)
    return image.astype('float32'), nodata

###############################################################
# Model                                                       #
###############################################################
def load_models(model_path, device):
    if os.path.isfile(model_path):
        model_files = [model_path]
    else:
        model_files = sorted(glob(os.path.join(model_path, '*.pth')))
    if len(model_files) == 0:
        raise FileNotFoundError('No .pth file found in %s' % model_path)

    models = []
    for model_file in model_files:
        print('Loading model: %s' % model_file)
        model = MariNext(11, len(labels))
        checkpoint = torch.load(model_file, map_location=device)
        checkpoint = {k.replace('decoder', 'decode_head'): v for k, v in checkpoint.items()
                      if ('proj1' not in k) and ('proj2' not in k)}
        model.load_state_dict(checkpoint)
        model.to(device)
        model.eval()
        models.append(model)
    return models

def predict_tiles(models, tiles, tta):
    '''(B, 11, T, T) -> softmax probabilities (B, 15, T, T), averaged over models and TTA.'''
    variants = [(k, flip) for k in range(4) for flip in (False, True)] if tta else [(0, False)]
    probs = 0
    for model in models:
        for k, flip in variants:
            x = torch.rot90(tiles, k, dims=[-2, -1])
            if flip:
                x = torch.flip(x, dims=[-1])

            logits = model(x)
            logits = F.interpolate(logits, size=x.shape[-2:], mode='bilinear', align_corners=False)
            p = torch.softmax(logits, dim=1)

            # Undo the augmentation so all predictions are aligned
            if flip:
                p = torch.flip(p, dims=[-1])
            p = torch.rot90(p, -k, dims=[-2, -1])
            probs = probs + p
    return probs / (len(models) * len(variants))

def window_starts(size, stride):
    starts = list(range(0, size - TILE + 1, stride))
    if starts[-1] + TILE < size:
        starts.append(size - TILE)
    return starts

def sliding_window(image, models, device, stride, batch, tta):
    '''Predicts overlapping 240x240 windows and averages the overlaps.'''
    C, H, W = image.shape

    # Images smaller than one tile are padded with 0 (= band mean after standardization)
    image = np.pad(image, ((0, 0), (0, max(TILE - H, 0)), (0, max(TILE - W, 0))), mode='constant')
    Hp, Wp = image.shape[1:]

    positions = [(y, x) for y in window_starts(Hp, stride) for x in window_starts(Wp, stride)]
    prob_sum = np.zeros((len(labels), Hp, Wp), dtype=np.float32)
    weight = np.zeros((Hp, Wp), dtype=np.float32)

    with torch.no_grad():
        for i in tqdm(range(0, len(positions), batch), desc='predicting'):
            chunk = positions[i:i + batch]
            tiles = np.stack([image[:, y:y + TILE, x:x + TILE] for y, x in chunk])
            probs = predict_tiles(models, torch.from_numpy(tiles).to(device), tta).cpu().numpy()

            for (y, x), p in zip(chunk, probs):
                prob_sum[:, y:y + TILE, x:x + TILE] += p
                weight[y:y + TILE, x:x + TILE] += 1

    return prob_sum[:, :H, :W] / weight[:H, :W]

###############################################################
# Output                                                      #
###############################################################
def write_tif(path, array, profile, dtype, nodata):
    out_profile = profile.copy()
    out_profile.update(driver='GTiff', count=1, dtype=dtype, nodata=nodata, compress='lzw')
    with rasterio.open(path, 'w', **out_profile) as dst:
        dst.write(array.astype(dtype), 1)

def write_qml(path, entries):
    '''entries: (value, hex colour, alpha 0-255, label) for each class.'''
    rows = '\n'.join('        <paletteEntry value="%d" color="%s" alpha="%d" label=%s/>'
                     % (value, color, alpha, quoteattr(label)) for value, color, alpha, label in entries)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(QML_TEMPLATE % rows)

def write_styles(output):
    '''Class names and MADOS colours for classes.tif, transparent background for oil_spill_mask.tif.'''
    write_qml(os.path.join(output, 'classes.qml'),
              [(c, CLASS_COLORS[c - 1], 255, '%d - %s' % (c, name)) for c, name in enumerate(labels, 1)])
    write_qml(os.path.join(output, 'oil_spill_mask.qml'),
              [(0, '#000000', 0, 'Not oil'), (1, '#ff00ff', 255, 'Oil Spill')])

def main(options):
    # The Hamburger decoder initialises its NMF bases randomly at every forward pass
    torch.manual_seed(0)

    if torch.cuda.is_available():
        device = torch.device("cuda")
    else:
        device = torch.device("cpu")

    image, profile = load_image(options['input'])
    print('Input size: %d bands x %d x %d pixels' % image.shape)
    image, nodata = preprocess(image)

    models = load_models(options['model_path'], device)
    probs = sliding_window(image, models, device, options['stride'], options['batch'], options['tta'])

    classes = probs.argmax(0).astype(np.uint8) + 1      # 1..15 as in MADOS, 0 = no data
    classes[nodata] = 0
    oil_mask = (classes == OIL_SPILL).astype(np.uint8)
    oil_mask[nodata] = 255
    oil_prob = probs[OIL_SPILL - 1].copy()
    oil_prob[nodata] = np.nan

    os.makedirs(options['output'], exist_ok=True)
    write_tif(os.path.join(options['output'], 'classes.tif'), classes, profile, 'uint8', 0)
    write_tif(os.path.join(options['output'], 'oil_spill_mask.tif'), oil_mask, profile, 'uint8', 255)
    write_tif(os.path.join(options['output'], 'oil_spill_prob.tif'), oil_prob, profile, 'float32', np.nan)
    write_styles(options['output'])

    # Summary
    n_valid = int((~nodata).sum())
    print('\nPredicted classes (%d valid pixels):' % n_valid)
    for c, name in enumerate(labels, 1):
        n = int((classes == c).sum())
        if n > 0:
            print('  %-26s %10d px  (%5.2f%%)' % (name, n, 100.0 * n / max(n_valid, 1)))

    n_oil = int((oil_mask == 1).sum())
    crs = profile.get('crs')
    if crs is not None and crs.is_projected:
        pixel_area = abs(profile['transform'].a * profile['transform'].e)  # m2
        print('\nOil Spill: %d px = %.3f km2' % (n_oil, n_oil * pixel_area / 1e6))
    else:
        print('\nOil Spill: %d px (no projected CRS, area not computed)' % n_oil)

    print('Outputs written to: %s' % options['output'])

if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument('--input', required=True, help='Folder with the 11 ACOLITE *rhorc_<nm>.tif bands, or one 11-band GeoTIFF')
    parser.add_argument('--model_path', default=os.path.join(up(os.path.abspath(__file__)), 'trained_models', '1'), help='Folder with .pth file(s) (several = ensemble) or a single .pth')
    parser.add_argument('--output', default=None, help='Output folder (default: data/predicted_s2/<input name>)')
    parser.add_argument('--stride', default=120, type=int, help='Step between 240x240 windows (smaller = more overlap, slower)')
    parser.add_argument('--batch', default=8, type=int, help='Number of windows predicted at once')
    parser.add_argument('--tta', default=False, type=bool_flag, help='Test-time augmentation (8x slower)')

    args = parser.parse_args()
    options = vars(args)  # convert to ordinary dict

    if options['output'] is None:
        input_name = os.path.splitext(os.path.basename(os.path.normpath(options['input'])))[0]
        options['output'] = os.path.join(root_path, 'data', 'predicted_s2', input_name)

    main(options)
