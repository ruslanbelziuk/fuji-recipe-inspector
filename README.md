# fuji-recipe-inspector

A tool to extract EXIF data from Fujifilm camera images and convert them to FP1 (Fuji Recipe Profile) XML format.

## Features

- Extract all EXIF data from images (debug mode)
- Convert EXIF data to Fuji FP1 XML format
- Support for Fujifilm film simulations, white balance, and picture settings
- Works on macOS and Linux

## Requirements

- `exiftool` must be installed
  - macOS: `brew install exiftool`
  - Linux (Debian/Ubuntu): `sudo apt-get install libimage-exiftool-perl`
  - Linux (RHEL/CentOS): `sudo yum install perl-Image-ExifTool`

## Usage

### Generate FP1 XML from image

```bash
./fuji-recipe-inspector photo.jpg > recipe.FP1
```

### Debug mode - show all EXIF data

```bash
./fuji-recipe-inspector --debug photo.jpg
```

### Help

```bash
./fuji-recipe-inspector --help
```

## Supported EXIF Fields

The script extracts and maps the following EXIF data to FP1 format:

- Camera model
- Film simulation mode
- White balance
- Exposure compensation
- Dynamic range
- Highlight/Shadow tone
- Color saturation
- Sharpness
- Noise reduction
- Grain effect and size
- Color Chrome effects
- Clarity

## Output Format

The script generates XML in the Fuji FP1 format compatible with X RAW Studio and other Fujifilm software. The generated profiles can be imported and applied to RAW files.
