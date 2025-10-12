#!/opt/homebrew/bin/python3.10
"""
Script: fuji-recipe-inspector.py
Description: Extract EXIF data from images and convert to Fuji FP1 XML format
"""

import sys
import os
import re
import argparse
import hashlib
import json
import photoscript
import subprocess
import shutil
import tempfile
from pathlib import Path
from typing import Optional, Dict, List, Any
import xml.etree.ElementTree as ET

try:
    from osxphotos import PhotosDB, QueryOptions, PhotoInfo
    from osxphotos.photosalbum import PhotosAlbum
    OSXPHOTOS_AVAILABLE = True
except ImportError:
    OSXPHOTOS_AVAILABLE = False

VERSION = "0.0.1-dev"

FUJI_RECIPE_COMMENT_PREFIX = "[FUJI_RECIPE]"
FUJI_RECIPE_COMMENT_SUFFIX = "[/FUJI_RECIPE]"

class FujiRecipeInspector:
    """Extract and convert Fujifilm recipe data from images."""

    bw_film_simulations = ["Acros", "AcrosYe", "AcrosR", "AcrosG", "BYe", "BR", "BG", "Sepia", "BW"]

    def __init__(self, image_file: str):
        self.image_file = image_file
        self.exif_data: Dict[str, Any] = {}
        self._check_dependencies()
        self._load_exif()

    def _check_dependencies(self):
        """Check if exiftool is installed."""
        if not shutil.which('exiftool'):
            print("Error: exiftool is not installed", file=sys.stderr)
            print("", file=sys.stderr)
            print("Install it with:", file=sys.stderr)
            if sys.platform == 'darwin':
                print("  brew install exiftool", file=sys.stderr)
            sys.exit(1)

    def _load_exif(self):
        """Load EXIF data from image file using exiftool."""
        if not os.path.isfile(self.image_file):
            raise FileNotFoundError(f"File not found: {self.image_file}")

        try:
            result = subprocess.run(
                ['exiftool', '-json', '-groupNames', '-s3', self.image_file],
                capture_output=True,
                text=True,
                check=True
            )
            data = json.loads(result.stdout)
            if data and len(data) > 0:
                self.exif_data = data[0]
        except subprocess.CalledProcessError:
            self.exif_data = {}
        except json.JSONDecodeError:
            self.exif_data = {}

    def get_exif_value(self, tag: str, default: str = "",
                       uppercase: bool = False, category: str = "MakerNotes") -> str:
        """Extract EXIF value with optional category prefix."""
        # Try with category prefix first
        full_tag = f"{category}:{tag}"
        value = None

        if full_tag in self.exif_data:
            value = self.exif_data[full_tag]
        elif tag in self.exif_data:
            value = self.exif_data[tag]

        if value is None or value == "":
            return default

        # Convert to string if not already
        value = str(value)

        return value.upper() if uppercase else value

    def extract_numeric(self, value: str) -> str:
        """Extract numeric part from value strings like '+3 (very high)' -> '3'."""
        if not value:
            return value

        match = re.search(r'[+-]?\d+\.?\d*', value)
        if match:
            num = match.group(0)
            return num.lstrip('+')

        return "0"

    def format_exposure_bias(self, value: str) -> str:
        """Format exposure bias to FP1 format (e.g., 'P0P33' or 'M1P00')."""
        if not value or value == "0" or value == "0.0":
            return "0"

        try:
            num_value = float(value)
        except ValueError:
            return "0"

        # Determine sign
        sign = "P" if num_value >= 0 else "M"
        num_value = abs(num_value)

        # Split into integer and decimal parts
        int_part = int(num_value)
        dec_part = int((num_value - int_part) * 100)

        return f"{sign}{int_part}P{dec_part:02d}"

    def parse_wb_shift(self, wb_fine_tune: str, color: str) -> str:
        """Parse WB shift from fine tune string."""
        if not wb_fine_tune:
            return "0"

        pattern = f"{color.title()} ([+-]?\\d+)"
        match = re.search(pattern, wb_fine_tune, re.IGNORECASE)

        if match:
            value = int(match.group(1))
            return str(value // 20)

        return "0"

    def map_film_simulation(self, film: str) -> str:
        """Map film simulation name to FP1 code."""
        if not film:
            return ""

        film = film.lower()

        mapping = {
            "provia": "Provia",
            "velvia": "Velvia",
            "astia": "Astia",
            "classic chrome": "Classic",
            "pro neg. hi": "NEGAhi",
            "pro neg. std": "NEGAStd",
            "classic neg": "ClassicNEGA",
            "eterna": "Eterna",
            "bleach bypass": "BleachBypass",
            "nostalgic neg": "NostalgicNEGA",
            "reala": "Reala",
            "acros+ye": "AcrosYe",
            "acros ye": "AcrosYe",
            "acros+r": "AcrosR",
            "acros r": "AcrosR",
            "acros+g": "AcrosG",
            "acros g": "AcrosG",
            "acros": "Acros",
            "sepia": "Sepia",
            "b&w": "BW",
            "bw": "BW",
            "monochrome": "BW",
        }

        for key, value in mapping.items():
            if key in film:
                return value

        return ""

    def map_saturation_bw(self, saturation: str) -> str:
        """Map saturation/BW filter to film simulation."""
        if not saturation:
            return ""

        saturation = saturation.lower()

        mapping = {
            "acros yellow": "AcrosYe",
            "acros red": "AcrosR",
            "acros green": "AcrosG",
            "acros": "Acros",
            "b&w yellow": "BYe",
            "bw yellow": "BYe",
            "b&w red": "BR",
            "bw red": "BR",
            "b&w green": "BG",
            "bw green": "BG",
            "b&w sepia": "Sepia",
            "bw sepia": "Sepia",
            "none (b&w)": "BW",
        }

        for key, value in mapping.items():
            if key in saturation:
                return value

        return ""

    def map_white_balance(self, wb: str) -> str:
        """Map white balance name to FP1 code."""
        if not wb:
            return "Auto"

        wb = wb.lower()

        mapping = {
            "auto (white priority)": "Auto_White",
            "auto white": "Auto_White",
            "auto (ambiance priority)": "Auto_Ambience",
            "auto ambiance": "Auto_Ambience",
            "auto": "Auto",
            "custom3": "Custom3",
            "custom2": "Custom2",
            "custom": "Custom1",
            "kelvin": "Temperature",
            "daylight fluorescent": "FLight1",
            "day white fluorescent": "FLight2",
            "white fluorescent": "FLight3",
            "daylight": "Daylight",
            "cloudy": "Shade",
            "incandescent": "Incand",
            "underwater": "UWater",
        }

        for key, value in mapping.items():
            if key in wb:
                return value

        return "Auto"

    def film_sim_to_readable(self, code: str) -> str:
        """Convert FP1 film simulation code to readable name."""
        mapping = {
            "Provia": "Provia/Standard",
            "Velvia": "Velvia/Vivid",
            "Astia": "Astia/Soft",
            "Classic": "Classic Chrome",
            "NEGAhi": "PRO Neg. Hi",
            "NEGAStd": "PRO Neg. Std",
            "ClassicNEGA": "Classic Negative",
            "Eterna": "Eterna/Cinema",
            "BleachBypass": "Eterna Bleach Bypass",
            "NostalgicNEGA": "Nostalgic Negative",
            "Reala": "Reala Ace",
            "Acros": "Acros",
            "AcrosR": "Acros+R",
            "AcrosG": "Acros+G",
            "AcrosYe": "Acros+Ye",
            "Sepia": "Sepia",
            "BW": "Monochrome",
            "BR": "Monochrome+R",
            "BG": "Monochrome+G",
            "BYe": "Monochrome+Ye",
        }
        return mapping.get(code, code)

    def wb_to_readable(self, code: str) -> str:
        """Convert FP1 white balance code to readable name."""
        mapping = {
            "Auto": "Auto",
            "Auto_White": "Auto (White Priority)",
            "Auto_Ambience": "Auto (Ambiance Priority)",
            "Custom1": "Custom",
            "Custom2": "Custom 2",
            "Custom3": "Custom 3",
            "Temperature": "Kelvin",
            "FLight1": "Daylight Fluorescent",
            "FLight2": "Day White Fluorescent",
            "FLight3": "White Fluorescent",
            "Daylight": "Daylight",
            "Shade": "Cloudy",
            "Incand": "Incandescent",
            "UWater": "Underwater",
        }
        return mapping.get(code, code)

    def exposure_to_readable(self, value: str) -> str:
        """Convert exposure bias format to readable (e.g., 'P0P33' -> '+0 1/3')."""
        if not value or value == "0":
            return "0"

        # Parse format like "P0P33" or "M1P00"
        match = re.match(r'([PM])(\d+)P(\d+)', value)
        if not match:
            return value

        sign_char, int_part, dec_part = match.groups()
        sign = "-" if sign_char == "M" else "+"

        # Special case: if int_part is 0 and sign is +, omit the sign
        if int_part == "0" and sign == "+":
            if dec_part == "00":
                return "0"
            elif dec_part == "33":
                return "1/3"
            elif dec_part == "67":
                return "2/3"
            else:
                return f"0.{dec_part}"

        if int_part == "0" and sign == "-":
            if dec_part == "00":
                return "0"
            elif dec_part == "33":
                return "-1/3"
            elif dec_part == "67":
                return "-2/3"
            else:
                return f"-0.{dec_part}"

        if dec_part == "00":
            return f"{sign}{int_part}"
        elif dec_part == "33":
            return f"{sign}{int_part} 1/3"
        elif dec_part == "67":
            return f"{sign}{int_part} 2/3"
        else:
            return f"{sign}{int_part}.{dec_part}"

    def generate_fp1(self) -> tuple[str, str]:
        """Generate FP1 XML from image EXIF data.
        
        Returns:
            tuple[str, str]: (xml_string, hash_value) where hash_value is calculated
                            from PropertyGroup content only (excluding attributes)
        """
        # Check if this is a Fujifilm camera
        fuji_model = self.get_exif_value("FujiModel", "")
        if not fuji_model:
            raise ValueError("Not a Fujifilm image")

        # Extract camera model
        camera_model = fuji_model.split('_')[0] if '_' in fuji_model else ""
        if not camera_model:
            camera_model = self.get_exif_value("Model", "", category="Image")

        # Film simulation
        film_sim_raw = self.get_exif_value("FilmMode", "")
        film_simulation = self.map_film_simulation(film_sim_raw)

        # If FilmMode is empty, check Saturation for B&W recipes
        if not film_simulation:
            saturation_raw = self.get_exif_value("Saturation", "")
            film_simulation = self.map_saturation_bw(saturation_raw)

        # White balance
        wb_raw = self.get_exif_value("WhiteBalance", "Auto")
        white_balance = self.map_white_balance(wb_raw)

        # WB temperature
        if white_balance == "Temperature":
            color_temp = self.get_exif_value("ColorTemperature", "5500")
            wb_temp = f"{color_temp}K"
        else:
            wb_temp = self.get_exif_value("WB_RGBLevels", "5500K")

        # WB shift
        wb_fine_tune = self.get_exif_value("WhiteBalanceFineTune", "Red +0, Blue +0")
        wb_shift_r = self.parse_wb_shift(wb_fine_tune, "red")
        wb_shift_b = self.parse_wb_shift(wb_fine_tune, "blue")

        # Exposure bias
        exposure_comp = self.get_exif_value("ExposureCompensation", "0", category="EXIF")
        exposure_bias = self.format_exposure_bias(self.extract_numeric(exposure_comp))

        # Dynamic range
        dynamic_range = self.get_exif_value("DevelopmentDynamicRange", "")
        dynamic_range_setting = self.get_exif_value("DynamicRangeSetting", "")
        if (not dynamic_range) or dynamic_range_setting == "Auto":
            dynamic_range = "Auto"

        # Tone and color settings
        highlight_tone = self.extract_numeric(self.get_exif_value("HighlightTone", "0"))
        shadow_tone = self.extract_numeric(self.get_exif_value("ShadowTone", "0"))
        color = self.extract_numeric(self.get_exif_value("Saturation", "0"))
        sharpness = self.extract_numeric(self.get_exif_value("Sharpness", "0"))
        noise_reduction = self.extract_numeric(self.get_exif_value("NoiseReduction", "0"))
        clarity = self.extract_numeric(self.get_exif_value("Clarity", "0"))

        # B&W adjustments
        bw_adjustment = self.extract_numeric(self.get_exif_value("BWAdjustment", "0"))
        bw_magenta_green = self.extract_numeric(self.get_exif_value("BWMagentaGreen", "0"))

        # Grain effect
        grain_effect = self.get_exif_value("GrainEffectRoughness", "OFF", uppercase=True)
        grain_size = self.get_exif_value("GrainEffectSize", "OFF", uppercase=True)

        # Color chrome
        color_chrome = self.get_exif_value("ColorChromeEffect", "OFF", uppercase=True)
        color_chrome_blue = self.get_exif_value("ColorChromeFXBlue", "OFF", uppercase=True)

        # Generate label from filename
        filename = os.path.basename(self.image_file)
        label = os.path.splitext(filename)[0]

        # Serial number (placeholder)
        serial_number = "000000000000000000000000000000"

        # Camera version
        camera_version = fuji_model if fuji_model else f"{camera_model.replace(' ', '-')}_0100"

        properties_xml = f'''
        <DynamicRange>{dynamic_range}</DynamicRange>
        <WideDRange>0</WideDRange>
        <FilmSimulation>{film_simulation}</FilmSimulation>
        <BlackImageTone>{bw_adjustment}</BlackImageTone>
        <MonochromaticColor_RG>{bw_magenta_green}</MonochromaticColor_RG>
        <GrainEffect>{grain_effect}</GrainEffect>
        <GrainEffectSize>{grain_size}</GrainEffectSize>
        <ChromeEffect>{color_chrome}</ChromeEffect>
        <ColorChromeBlue>{color_chrome_blue}</ColorChromeBlue>
        <SmoothSkinEffect>OFF</SmoothSkinEffect>
        <WBShootCond>OFF</WBShootCond>
        <WhiteBalance>{white_balance}</WhiteBalance>
        <WBShiftR>{wb_shift_r}</WBShiftR>
        <WBShiftB>{wb_shift_b}</WBShiftB>
        <WBColorTemp>{wb_temp}</WBColorTemp>
        <HighlightTone>{highlight_tone}</HighlightTone>
        <ShadowTone>{shadow_tone}</ShadowTone>
        <Color>{color}</Color>
        <Sharpness>{sharpness}</Sharpness>'''

        xml = f'''<?xml version="1.0" encoding="utf-8"?>
<ConversionProfile application="XRFC" version="1.12.0.0">
    <PropertyGroup device="{camera_model}" version="{camera_version}" label="{label}">
        <SerialNumber>{serial_number}</SerialNumber>
        <TetherRAWConditonCode>{camera_version}</TetherRAWConditonCode>
        <Editable>TRUE</Editable>
        <SourceFileName/>
        <Fileerror>NONE</Fileerror>
        <RotationAngle>0</RotationAngle>
        <StructVer>65536</StructVer>
        <IOPCode>FF159509</IOPCode>
        <ShootingCondition>OFF</ShootingCondition>
        <FileType>JPG</FileType>
        <ImageSize>L3x2</ImageSize>
        <ImageQuality>Fine</ImageQuality>
        <ExposureBias>{exposure_bias}</ExposureBias>{properties_xml}
        <NoisReduction>{noise_reduction}</NoisReduction>
        <Clarity>{clarity}</Clarity>
        <LensModulationOpt>ON</LensModulationOpt>
        <ColorSpace>sRGB</ColorSpace>
        <HDR/>
        <DigitalTeleConv>OFF</DigitalTeleConv>
        <PortraitEnhancer/>
    </PropertyGroup>
</ConversionProfile>'''

        hash_value = hashlib.sha256(properties_xml.encode('utf-8')).hexdigest()[:8]

        return xml, hash_value

    def extract_xml_field(self, xml_content: str, field_name: str) -> str:
        """Extract field value from XML."""
        try:
            root = ET.fromstring(xml_content)
            element = root.find(f".//PropertyGroup/{field_name}")
            return element.text if element is not None and element.text else ""
        except:
            return ""

    def get_mandatory_fields(self) -> List[str]:
        """Get list of mandatory fields for recipe matching."""
        return [
            "FilmSimulation",
            "WBShiftR",
            "WBShiftB",
            "WhiteBalance",
            "WBColorTemp",
            "ChromeEffect",
            "ColorChromeBlue",
            "HighlightTone",
            "ShadowTone",
            "DynamicRange",
            "Color",
            "Sharpness",
            "NoisReduction",
            "BlackImageTone",
            "MonochromaticColor_RG",
        ]

    def values_match(self, field: str, val1: str, val2: str, tolerance: float = 0.1) -> bool:
        """Compare two values with fuzzy matching for numeric fields."""
        # Empty value handling
        if not val1 and not val2:
            return True
        if not val1 or not val2:
            return False

        # Exact match
        if val1 == val2:
            return True

        # Numeric comparison
        try:
            num1 = float(val1)
            num2 = float(val2)
            return abs(num1 - num2) <= tolerance

        except ValueError:
            return False

    def compare_recipes(self, generated_xml: str, recipe_file: str) -> Optional[str]:
        """Compare generated XML with a recipe FP1 file."""
        if not os.path.isfile(recipe_file):
            return None

        with open(recipe_file, 'r', encoding='utf-8') as f:
            recipe_xml = f.read()

        recipe_name = os.path.splitext(os.path.basename(recipe_file))[0]
        mandatory_fields = self.get_mandatory_fields()

        film_simulation = self.extract_xml_field(generated_xml, "FilmSimulation")

        for field in mandatory_fields:
            generated_value = self.extract_xml_field(generated_xml, field)
            recipe_value = self.extract_xml_field(recipe_xml, field)

            if field == "WBColorTemp":
                # Skip WBColorTemp if WhiteBalance is not Temperature
                wb_value = self.extract_xml_field(generated_xml, "WhiteBalance")
                if wb_value != "Temperature":
                    continue

                generated_value = generated_value.upper()
                recipe_value = recipe_value.upper()

            # Set tolerance based on field type
            tolerance = 0.5 if field in ["HighlightTone", "ShadowTone"] else 0.1

            if not self.values_match(field, generated_value, recipe_value, tolerance):
                if field == "Color" and film_simulation in self.bw_film_simulations:
                    continue

                if field in ["BlackImageTone", "MonochromaticColor_RG"]:
                    if recipe_value == "":
                        continue

                    if film_simulation not in self.bw_film_simulations:
                        continue

                if field == "DynamicRange" and recipe_value == "Auto":
                    continue

                # For X-Trans IV compatibility
                if field == "ColorChromeBlue":
                    if (generated_value == "WEAK" and recipe_value == "OFF") or (generated_value == "STRONG" and recipe_value == "WEAK"):
                        continue

                return None

        return recipe_name

    def find_matching_recipe(self) -> Optional[str]:
        """Find matching recipe from FP1 files."""
        try:
            generated_xml, hash_value = self.generate_fp1()
        except:
            return None

        fp1_files = self.get_fp1_files()
        if not fp1_files:
            return None

        for recipe_file in fp1_files:
            result = self.compare_recipes(generated_xml, recipe_file)
            if result:
                return result

        if hash_value:
            return f"Unknown ({hash_value})"
        
        return "Unknown"

    def get_fp1_files(self) -> List[str]:
        """Get all FP1 files from X RAW STUDIO folder and Recipes directory."""
        found_files = []

        # Check X RAW STUDIO directory
        xraw_dir = Path.home() / "Library/Application Support/com.fujifilm.denji/X RAW STUDIO"
        if xraw_dir.exists():
            found_files.extend(str(f) for f in xraw_dir.rglob("*.FP1"))

        # Check local Recipes directory
        script_dir = Path(__file__).parent
        recipes_dir = script_dir / "recipes"
        if recipes_dir.exists():
            found_files.extend(str(f) for f in recipes_dir.rglob("*.FP1"))

        return found_files

    def generate_readable_format(self) -> str:
        """Generate human-readable recipe format."""
        # Check if this is a Fujifilm camera
        fuji_model = self.get_exif_value("FujiModel", "")
        if not fuji_model:
            raise ValueError("Not a Fujifilm image")

        # Find recipe name
        recipe_name = self.find_matching_recipe()
        if not recipe_name:
            recipe_name = "Unknown"

        # Extract all values
        film_sim_raw = self.get_exif_value("FilmMode", "")
        film_simulation = self.map_film_simulation(film_sim_raw)

        if not film_simulation:
            saturation_raw = self.get_exif_value("Saturation", "")
            film_simulation = self.map_saturation_bw(saturation_raw)

        film_sim_readable = self.film_sim_to_readable(film_simulation)

        # White balance
        wb_raw = self.get_exif_value("WhiteBalance", "Auto")
        white_balance = self.map_white_balance(wb_raw)
        wb_readable = self.wb_to_readable(white_balance)
        color_temp = self.get_exif_value("ColorTemperature", "0")
        wb_temp = f"{color_temp}K"

        # WB shift
        wb_fine_tune = self.get_exif_value("WhiteBalanceFineTune", "Red +0, Blue +0")
        wb_shift_r = int(self.parse_wb_shift(wb_fine_tune, "red"))
        wb_shift_b = int(self.parse_wb_shift(wb_fine_tune, "blue"))

        if wb_shift_r != 0 or wb_shift_b != 0:
            wb_shift_r_str = f"+{wb_shift_r}" if wb_shift_r >= 0 else str(wb_shift_r)
            wb_shift_b_str = f"+{wb_shift_b}" if wb_shift_b >= 0 else str(wb_shift_b)
            wb_shift = f"{wb_shift_r_str} Red, {wb_shift_b_str} Blue"
        else:
            wb_shift = "0"

        # Dynamic range
        dynamic_range = self.get_exif_value("DevelopmentDynamicRange", "")
        if not dynamic_range:
            dynamic_range = self.get_exif_value("AutoDynamicRange", "100")
            dynamic_range = dynamic_range.rstrip('%')
        if "DR" not in dynamic_range:
            dynamic_range = f"DR{dynamic_range}"

        # Tone and color
        highlight_tone = self.extract_numeric(self.get_exif_value("HighlightTone", "0"))
        shadow_tone = self.extract_numeric(self.get_exif_value("ShadowTone", "0"))
        color = self.extract_numeric(self.get_exif_value("Saturation", "0"))
        sharpness = self.extract_numeric(self.get_exif_value("Sharpness", "0"))
        noise_reduction = self.extract_numeric(self.get_exif_value("NoiseReduction", "0"))
        clarity = self.extract_numeric(self.get_exif_value("Clarity", "0"))

        # B&W adjustments
        bw_adjustment = int(self.extract_numeric(self.get_exif_value("BWAdjustment", "0")))
        bw_magenta_green = int(self.extract_numeric(self.get_exif_value("BWMagentaGreen", "0")))

        mono_shift = None
        if bw_adjustment != 0 or bw_magenta_green != 0:
            bw_adj_str = f"+{bw_adjustment}" if bw_adjustment >= 0 else str(bw_adjustment)
            bw_mg_str = f"+{bw_magenta_green}" if bw_magenta_green >= 0 else str(bw_magenta_green)
            mono_shift = f"WC {bw_adj_str}, MG {bw_mg_str}"

        # Grain effect
        grain_effect = self.get_exif_value("GrainEffectRoughness", "OFF")
        grain_size = self.get_exif_value("GrainEffectSize", "OFF")

        if grain_effect.upper() not in ["OFF", ""]:
            grain_text = grain_effect
            if grain_size.upper() not in ["OFF", ""]:
                grain_text = f"{grain_effect}, {grain_size}"
        else:
            grain_text = "Off"

        # Color chrome
        color_chrome = self.get_exif_value("ColorChromeEffect", "OFF")
        color_chrome_blue = self.get_exif_value("ColorChromeFXBlue", "OFF")

        # Exposure bias
        exposure_comp = self.get_exif_value("ExposureCompensation", "0", category="EXIF")
        exposure_bias_raw = self.format_exposure_bias(self.extract_numeric(exposure_comp))
        exposure_readable = self.exposure_to_readable(exposure_bias_raw)

        # Build output
        output = f"""{FUJI_RECIPE_COMMENT_PREFIX}
Film Recipe: {recipe_name}
Simulation: {film_sim_readable}
Grain Effect: {grain_text}
Colour Chrome Effect: {color_chrome}
Colour Chrome Blue: {color_chrome_blue}
White Balance: {wb_readable}"""

        if wb_readable == "Kelvin":
            output += f"\nColor Temperature: {wb_temp}"

        output += f"""
WB Shift: {wb_shift}
Dynamic Range: {dynamic_range}
Highlights: {highlight_tone}
Shadows: {shadow_tone}
Color: {color}
Sharpness: {sharpness}
ISO Noise Reduction: {noise_reduction}
Clarity: {clarity}"""

        # Conditionally add Mono Shift
        if mono_shift is not None:
            output += f"\nMono Shift: {mono_shift}"

        output += f"\nEV Compensation: {exposure_readable}\n{FUJI_RECIPE_COMMENT_SUFFIX}"

        return output

    def debug_mode(self):
        """Output all available Fujifilm EXIF data."""
        if not os.path.isfile(self.image_file):
            print(f"Error: File not found: {self.image_file}", file=sys.stderr)
            sys.exit(1)

        print(f"=== Fujifilm EXIF Data for: {self.image_file} ===\n", file=sys.stderr)

        # Use exiftool directly for debug output
        try:
            subprocess.run(
                ['exiftool', '-Fujifilm:all', self.image_file],
                check=True
            )
        except subprocess.CalledProcessError as e:
            print(f"Error running exiftool: {e}", file=sys.stderr)


def add_fujifilm_recipe_description_to_photos(photos: list[PhotoInfo], max_photos: int = 10000):
    """Add Fujifilm recipe description to photo description/caption
    
    Args:
        photos: List of photos to process
        max_photos: Maximum number of photos to process (excluding skipped ones)
    """
    processed_count = 0

    tempdir = tempfile.TemporaryDirectory()
    downloaded = 0
    exported = []
    
    for photo in photos:
        if photo.shared:
            continue

        if photo.exif_info.camera_make != "FUJIFILM":
            continue

        for filename in exported:
            print(f"Removing temporary file {filename}")
            os.unlink(filename)
        exported = []

        existing_description = photo.description or "" # description can be None
        if FUJI_RECIPE_COMMENT_PREFIX in existing_description and "Film Recipe: Unknown" not in existing_description:
            # print(f"Skipping {photo.original_filename} ({photo.uuid}) (Recipe already in description)")
            continue

        if photo.ismissing:
            print(f"Downloading photo {photo.original_filename}")
            downloaded += 1

            exported = photo.export(tempdir.name, use_photos_export=True, timeout=600)
            if photo.hasadjustments:
                exported.extend(
                    photo.export(
                        tempdir.name, use_photos_export=True, edited=True, timeout=600
                    )
                )

        if "Film Recipe: Unknown" in existing_description:
            # remove all the content between tags "[FUJI_RECIPE]" and "[/FUJI_RECIPE]"
            existing_description = re.sub(re.escape(FUJI_RECIPE_COMMENT_PREFIX) + r'.*?' + re.escape(FUJI_RECIPE_COMMENT_SUFFIX), '', existing_description, flags=re.DOTALL)

        existing_description = existing_description.strip()

        photo_path = exported[0] if exported else photo.path

        if not os.path.exists(photo_path):
            print(f"Skipping {photo.original_filename} ({photo.uuid}) (File not found)")
            continue

        inspector = FujiRecipeInspector(photo_path)

        # Check if photo is in "Fuji Recipe. Custom" album
        if ("Fuji Recipe. Custom" in photo.albums) or ("Fuji Recipe / Custom" in photo.albums) or ("Custom" in photo.albums):
            recipe_name = "Custom"
        else:
            recipe_name = None

        try:
            recipe_description = inspector.generate_readable_format()
            # If recipe name is "Custom", update the description
            if recipe_name == "Custom":
                # Replace the recipe name in the description
                original_recipe = inspector.find_matching_recipe()
                recipe_description = recipe_description.replace(
                    f"Film Recipe: {original_recipe}",
                    f"Film Recipe: Custom"
                )
        except Exception as e:
            print(f"Error generating readable format for {photo.original_filename} ({photo.uuid}): {e}")
            continue

        if recipe_name is None:
            recipe_name = inspector.find_matching_recipe()

        new_desc = f"{existing_description}\n{recipe_description}" if existing_description else recipe_description
        # print(f"Updating caption for {photo.original_filename} ({photo.uuid}) to {new_desc}")
        update_description(photo, new_desc)

        album_name = "Fuji Recipe / " + recipe_name

        if not album_name in photo.albums and not recipe_name in photo.albums:
            print(f"Adding {photo.original_filename} ({photo.uuid}) to album {album_name}")
            album = PhotosAlbum(album_name, None, ' / ')
            album.add(photo)
            print(f"Added to album")

        processed_count += 1
        if processed_count >= max_photos:
            print(f"\nReached maximum of {max_photos} processed photos. Stopping.")
            break

    for filename in exported:
        print(f"Removing temporary file {filename}")
        os.unlink(filename)
    exported = []

    print(f"Downloaded {downloaded} photos")
    tempdir.cleanup()

def update_description(photo: PhotoInfo, new_desc: str):
    """Update photo caption"""
    try:
        photoscript.Photo(photo.uuid).description = new_desc
    except Exception as e:
        print(
            f"Error updating caption for {photo.original_filename} ({photo.uuid}): {e}"
        )

def main():
    parser = argparse.ArgumentParser(
        description="Extract EXIF data from Fujifilm images and display recipe information.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
EXAMPLES:
    # Extract recipe information in human-readable format
    %(prog)s photo.jpg

    # Use latest Fujifilm photo from Apple Photos
    %(prog)s --apple-photos

    # Get FP1 recipe name from image
    %(prog)s --recipe photo.jpg

    # Generate FP1 XML from image
    %(prog)s --xml photo.jpg > recipe.FP1

    # Debug mode - show all EXIF data
    %(prog)s --debug photo.jpg

REQUIREMENTS:
    - exiftool must be installed
      macOS: brew install exiftool
    - osxphotos (optional, for --apple-photos)
      pip install osxphotos
        """)

    parser.add_argument('image_file', nargs='?', help='Path to the image file to process')
    parser.add_argument('--apple-photos', action='store_true',
                        help='Use the latest Fujifilm photo from Apple Photos')
    parser.add_argument('--recipe', action='store_true',
                        help='Get FP1 recipe name from image')
    parser.add_argument('--xml', action='store_true',
                        help='Generate FP1 XML from image (output to stdout)')
    parser.add_argument('--debug', action='store_true',
                        help='Output all available EXIF data (raw format)')
    parser.add_argument('--version', action='version', version=f'%(prog)s {VERSION}')

    args = parser.parse_args()

    # Handle --apple-photos mode
    if args.apple_photos:
        print("Searching for the latest Fujifilm photo from Apple Photos...\n", file=sys.stderr)

        if not OSXPHOTOS_AVAILABLE:
            print("Error: osxphotos is not installed", file=sys.stderr)
            print("", file=sys.stderr)
            print("Install it with:", file=sys.stderr)
            print("  pip install osxphotos", file=sys.stderr)
            sys.exit(1)

        photosdb = PhotosDB()

        fujifilm_photos = photosdb.photos(
            images = True,
            movies = False,
            intrash = False,
        )

        print(f"Found {len(fujifilm_photos)} photos")
        fujifilm_photos = sorted(fujifilm_photos, key=lambda x: x.date, reverse=True)
        print(f"Processing {len(fujifilm_photos)} photos...")

        add_fujifilm_recipe_description_to_photos(fujifilm_photos)

        print("Done.")
        return

    try:
        inspector = FujiRecipeInspector(args.image_file)

        if args.debug:
            inspector.debug_mode()
        elif args.recipe:
            print(inspector.find_matching_recipe())
        elif args.xml:
            xml_output, _ = inspector.generate_fp1()
            print(xml_output)
        else:
            print(inspector.generate_readable_format())

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
