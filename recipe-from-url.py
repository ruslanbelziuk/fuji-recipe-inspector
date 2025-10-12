#!/usr/bin/env python3
"""
Script: recipe-from-url.py
Description: Download recipe content from URLs and convert to Fuji FP1 XML format using Claude Projects API
"""

import sys
import os
import json
import argparse
from pathlib import Path
from typing import Optional, Dict, List
import requests
from readability import Document
from bs4 import BeautifulSoup
from lxml import etree
from anthropic import Anthropic

VERSION = "0.2.0"

DEFAULT_RECIPE_FOLDER = "recipes"
CONFIG_FILE = "config.json"
XSD_SCHEMA_FILE = "fuji-recipe.xsd"

# System instructions for Claude
SYSTEM_INSTRUCTIONS = """You are a Fujifilm Custom Recipe Creator.

You will receive input in a random text format with all the custom settings.

You should output a valid XML-file that would 100% suit the fuji-recipe.xsd

For any confusions, please use the most modern camera settings (so if there's separate conditions, use the settings for X-Trans 5, X-Trans V, or just "V", or just "5") and settings for best conditions.

Black and white film simulations are Acros (Acros) and Monochrome (BW). Color suffix for them must only be added if it is explicitly mentioned in the input. If all the colors are listed, use general one without suffixes.
"Mono Shift: WC 2, MG 0" means BlackImageTone=2 and MonochromaticColor_RG=0

Use this as a head:
<ConversionProfile application="XRFC" version="1.12.0.0">
    <PropertyGroup device="X-S20" version="X-S20_0200" label="Absolute Portra">
        <SerialNumber>5935363935312506042D8510110193</SerialNumber>
        <TetherRAWConditonCode>X-S20_0200</TetherRAWConditonCode>
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

end with
        <LensModulationOpt>ON</LensModulationOpt>
        <ColorSpace>sRGB</ColorSpace>
        <HDR />
        <DigitalTeleConv />

The name of the file should be like "Absolute Portra.FP1"

For any empty values (but not for 0) use self-closing XML attributes (HDR, PortraitEnhancer)
But for ExposureBias, WideDRange, BlackImageTone, MonochromaticColor_RG use "0" as default values
For color temperature use uppercase "K"

ExposureBias should be calculated like "+1/3" should be turned to "P0P33", "-1 2/3" to "M1P66" (so, 33, 66, and always "P" between parts)

Only output the file in XML, do not add any comments. Do not say anything else."""


class RecipeDownloader:
    """Download and convert recipe URLs to FP1 files."""

    def __init__(self):
        self.config: Dict[str, str] = {}
        self.client: Optional[Anthropic] = None
        self.xsd_schema: Optional[str] = None
        self.xsd_schema_doc: Optional[etree.XMLSchema] = None

    def load_or_create_config(self) -> bool:
        """Load configuration from file or create it interactively."""
        config_path = Path(__file__).parent / CONFIG_FILE

        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
                print(f"✓ Loaded configuration from {config_path}")
                return True
            except Exception as e:
                print(f"Error loading config: {e}", file=sys.stderr)
                return False
        else:
            print("Configuration file not found. Let's set it up!\n")
            return self.create_config(config_path)

    def create_config(self, config_path: Path) -> bool:
        """Create configuration interactively."""
        print("=== First-Time Setup ===\n")

        # Claude API Key
        api_key = input("Enter your Claude API key: ").strip()
        if not api_key:
            print("Error: API key is required", file=sys.stderr)
            return False

        # Recipe folder
        print(f"\nDefault recipe folder: {DEFAULT_RECIPE_FOLDER} (relative to project)")
        custom_folder = input("Press Enter to use default, or enter a custom path: ").strip()
        recipe_folder = custom_folder if custom_folder else DEFAULT_RECIPE_FOLDER

        # Resolve relative path to absolute
        recipe_path = Path(recipe_folder)
        if not recipe_path.is_absolute():
            recipe_path = Path(__file__).parent / recipe_folder
        
        # Create folder if it doesn't exist
        if not recipe_path.exists():
            try:
                recipe_path.mkdir(parents=True, exist_ok=True)
                print(f"✓ Created folder: {recipe_path}")
            except Exception as e:
                print(f"Error creating folder: {e}", file=sys.stderr)
                return False

        # Save configuration (store as relative path if possible)
        self.config = {
            "claude_api_key": api_key,
            "recipe_folder": recipe_folder
        }

        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2)
            print(f"\n✓ Configuration saved to {config_path}")
            return True
        except Exception as e:
            print(f"Error saving config: {e}", file=sys.stderr)
            return False

    def initialize_client(self) -> bool:
        """Initialize Anthropic client."""
        try:
            self.client = Anthropic(api_key=self.config["claude_api_key"])
            return True
        except Exception as e:
            print(f"Error initializing Claude client: {e}", file=sys.stderr)
            return False

    def load_xsd_schema(self) -> bool:
        """Load and compile the XSD schema file."""
        schema_path = Path(__file__).parent / XSD_SCHEMA_FILE
        
        if not schema_path.exists():
            print(f"Error: XSD schema file not found: {schema_path}", file=sys.stderr)
            return False
        
        try:
            with open(schema_path, 'r', encoding='utf-8') as f:
                self.xsd_schema = f.read()
            
            # Parse and compile the XSD schema for validation
            schema_doc = etree.fromstring(self.xsd_schema.encode('utf-8'))
            self.xsd_schema_doc = etree.XMLSchema(schema_doc)
            
            print(f"✓ Loaded and compiled XSD schema from {schema_path}")
            return True
        except etree.XMLSchemaParseError as e:
            print(f"Error parsing XSD schema: {e}", file=sys.stderr)
            return False
        except Exception as e:
            print(f"Error loading XSD schema: {e}", file=sys.stderr)
            return False

    def download_url(self, url: str) -> Optional[str]:
        """Download and extract main content from URL."""
        try:
            print(f"Downloading {url}...")
            response = requests.get(url, timeout=30)
            response.raise_for_status()

            # Extract main content using readability
            doc = Document(response.text)
            title = doc.title()
            content_html = doc.summary()

            # Strip HTML tags and extract plain text
            soup = BeautifulSoup(content_html, 'html.parser')
            content_text = soup.get_text(separator='\n', strip=True)

            # Combine title and content
            full_text = f"Title: {title}\n\n{content_text}"
            print(f"✓ Downloaded and extracted content ({len(full_text)} characters)")
            return full_text

        except requests.RequestException as e:
            print(f"Error downloading URL: {e}", file=sys.stderr)
            return None
        except Exception as e:
            print(f"Error extracting content: {e}", file=sys.stderr)
            return None

    def send_to_claude(self, content: str) -> Optional[str]:
        """Send content to Claude API with system instructions and XSD schema."""
        try:
            print("Sending to Claude API...")
            
            # Prepare the user message with XSD schema and recipe content
            user_message = f"""Here is the XSD schema for Fujifilm FP1 recipe files:

```xml
{self.xsd_schema}
```

Now, please convert the following recipe content into a valid FP1 XML file:

{content}

Remember to:
1. Extract the recipe name and use it as the 'label' attribute
2. Parse all the camera settings mentioned
3. Use reasonable defaults for any settings not specified
4. Return only the XML, wrapped in ```xml code blocks
5. Ensure all values conform to the XSD schema"""

            # Use Messages API with system instructions
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=8000,
                system=SYSTEM_INSTRUCTIONS,
                messages=[
                    {
                        "role": "user",
                        "content": user_message
                    }
                ]
            )

            # Extract text from response
            xml_content = ""
            for block in response.content:
                if hasattr(block, 'text'):
                    xml_content += block.text

            print("✓ Received response from Claude")
            return xml_content

        except Exception as e:
            print(f"Error calling Claude API: {e}", file=sys.stderr)
            return None

    def extract_xml_from_response(self, response: str) -> Optional[str]:
        """Extract XML from Claude's response (may include markdown code blocks)."""
        # Try to extract from markdown code blocks
        if "```xml" in response:
            start = response.find("```xml") + 6
            end = response.find("```", start)
            xml_content = response[start:end].strip()
        elif "```" in response:
            start = response.find("```") + 3
            end = response.find("```", start)
            xml_content = response[start:end].strip()
        else:
            # Assume entire response is XML
            xml_content = response.strip()

        # Validate it starts with XML declaration or ConversionProfile
        if xml_content.startswith("<?xml") or xml_content.startswith("<ConversionProfile"):
            return xml_content
        
        print("Warning: Could not find valid XML in response", file=sys.stderr)
        return None

    def parse_label_from_xml(self, xml_content: str) -> Optional[str]:
        """Parse XML and extract label attribute from PropertyGroup."""
        try:
            root = etree.fromstring(xml_content.encode('utf-8'))
            property_group = root.find(".//PropertyGroup")
            
            if property_group is not None:
                label = property_group.get("label")
                if label:
                    return label
            
            print("Warning: Could not find label attribute in XML", file=sys.stderr)
            return None

        except etree.XMLSyntaxError as e:
            print(f"Error parsing XML: {e}", file=sys.stderr)
            return None
        except Exception as e:
            print(f"Error extracting label: {e}", file=sys.stderr)
            return None

    def validate_xml(self, xml_content: str) -> tuple[bool, Optional[str]]:
        """Validate XML content against XSD schema.
        
        Returns:
            tuple: (is_valid, error_message)
        """
        if not self.xsd_schema_doc:
            return False, "XSD schema not loaded"
        
        try:
            xml_doc = etree.fromstring(xml_content.encode('utf-8'))
            
            if self.xsd_schema_doc.validate(xml_doc):
                return True, None
            else:
                # Get detailed validation errors
                errors = []
                for error in self.xsd_schema_doc.error_log:
                    errors.append(f"Line {error.line}: {error.message}")
                return False, "\n".join(errors)
        
        except etree.XMLSyntaxError as e:
            return False, f"XML syntax error: {e}"
        except Exception as e:
            return False, f"Validation error: {e}"

    def add_url_comment(self, xml_content: str, url: str) -> str:
        """Add a comment with the source URL to the XML content."""
        try:
            # Parse the XML
            root = etree.fromstring(xml_content.encode('utf-8'))
            
            # Create a comment
            comment = etree.Comment(f"Simulation values parsed from {url}")
            
            # Insert comment as the first child of root
            root.insert(0, comment)
            
            # Add a newline after the comment for better formatting
            comment.tail = '\n    '
            
            # Return the XML with declaration
            xml_str = etree.tostring(root, pretty_print=True, encoding='unicode', xml_declaration=False)
            return f'<?xml version="1.0" encoding="utf-8"?>\n{xml_str}\n'
        except Exception as e:
            print(f"Warning: Could not add URL comment: {e}", file=sys.stderr)
            return xml_content

    def pretty_print_xml(self, xml_content: str) -> str:
        """Pretty print XML content."""
        try:
            root = etree.fromstring(xml_content.encode('utf-8'))
            return etree.tostring(root, pretty_print=True, encoding='unicode')
        except:
            return xml_content

    def save_recipe(self, filename: str, xml_content: str, auto_accept: bool = True) -> bool:
        """Save recipe to file with existence check.
        
        Args:
            filename: Name of the file to save
            xml_content: XML content to write
            auto_accept: If True, skip confirmation when file doesn't exist
        """
        recipe_folder = Path(self.config["recipe_folder"])
        
        # Resolve relative path
        if not recipe_folder.is_absolute():
            recipe_folder = Path(__file__).parent / recipe_folder
        
        # Ensure folder exists
        recipe_folder.mkdir(parents=True, exist_ok=True)
        
        file_path = recipe_folder / filename

        # Check if file exists
        if file_path.exists():
            print(f"\n⚠️  File already exists: {filename}")
            while True:
                choice = input("Enter new filename (or 'skip' to skip): ").strip()
                if choice.lower() == 'skip':
                    print("Skipping save.")
                    return False
                
                if not choice:
                    continue
                
                # Ensure .FP1 extension
                if not choice.endswith('.FP1'):
                    choice += '.FP1'
                
                new_path = recipe_folder / choice
                if new_path.exists():
                    print(f"⚠️  File {choice} also exists. Try another name.")
                    continue
                
                file_path = new_path
                filename = choice
                break

        # Save file
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(xml_content)
            print(f"✓ Saved recipe to: {file_path}")
            return True
        except Exception as e:
            print(f"Error saving file: {e}", file=sys.stderr)
            return False

    def process_url(self, url: str) -> bool:
        """Process a single URL through the complete workflow."""
        # Download and extract content
        content = self.download_url(url)
        if not content:
            return False

        # Send to Claude
        response = self.send_to_claude(content)
        if not response:
            return False

        # Extract XML
        xml_content = self.extract_xml_from_response(response)
        if not xml_content:
            print("Error: No valid XML found in response", file=sys.stderr)
            print("\nRaw response from Claude:", file=sys.stderr)
            print("-" * 60, file=sys.stderr)
            print(response, file=sys.stderr)
            print("-" * 60, file=sys.stderr)
            return False

        # Add URL comment to XML
        xml_content = self.add_url_comment(xml_content, url)

        # Validate XML against XSD schema
        print("Validating XML against schema...")
        is_valid, error_msg = self.validate_xml(xml_content)
        
        if not is_valid:
            print(f"\n⚠️  XML Validation Failed!", file=sys.stderr)
            print("Validation errors:", file=sys.stderr)
            print("-" * 60, file=sys.stderr)
            print(error_msg, file=sys.stderr)
            print("-" * 60, file=sys.stderr)
            
            # Ask user if they want to continue anyway
            continue_anyway = input("\nContinue anyway? (y/n): ").strip().lower()
            if continue_anyway != 'y':
                print("Discarded due to validation errors.")
                return False
        else:
            print("✓ XML validation passed")

        # Parse label
        label = self.parse_label_from_xml(xml_content)
        if not label:
            print("Error: Could not extract recipe name from XML", file=sys.stderr)

        # Generate filename
        filename = f"{label}.FP1"
        
        # Display results
        print("\n" + "=" * 60)
        print(f"Recipe Name: {label}")
        print(f"Filename: {filename}")
        print("=" * 60)

        # Auto-save (only prompts if file exists)
        return self.save_recipe(filename, xml_content)

    def read_urls_from_file(self, file_path: str) -> List[str]:
        """Read URLs from a file, one per line."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                urls = [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]
            return urls
        except FileNotFoundError:
            print(f"Error: File not found: {file_path}", file=sys.stderr)
            return []
        except Exception as e:
            print(f"Error reading file: {e}", file=sys.stderr)
            return []

    def process_batch(self, urls: List[str]) -> None:
        """Process a batch of URLs."""
        total = len(urls)
        successful = 0
        failed = 0
        
        print(f"\nProcessing {total} URL(s)...\n")
        
        for i, url in enumerate(urls, 1):
            print(f"\n[{i}/{total}] Processing: {url}")
            print("=" * 60)
            
            try:
                if self.process_url(url):
                    successful += 1
                else:
                    failed += 1
            except Exception as e:
                print(f"Error processing URL: {e}", file=sys.stderr)
                failed += 1
            
            print()  # Empty line between URLs
        
        # Summary
        print("\n" + "=" * 60)
        print("BATCH PROCESSING COMPLETE")
        print(f"Total: {total} | Successful: {successful} | Failed: {failed}")
        print("=" * 60)

    def run_interactive(self) -> None:
        """Run in interactive mode."""
        print("\nInteractive Mode")
        print("=" * 60)
        print("Options:")
        print("  - Enter a single URL to process it")
        print("  - Enter multiple URLs (paste them, then press Enter on empty line)")
        print("  - Type 'quit' or 'exit' to quit")
        print("=" * 60)
        print()

        # Main loop
        while True:
            try:
                print("Enter URL(s) (or 'quit' to exit):")
                urls = []
                
                # Read first line
                first_line = input().strip()
                
                if first_line.lower() in ['quit', 'exit', 'q']:
                    print("Goodbye!")
                    break
                
                if not first_line:
                    continue
                
                urls.append(first_line)
                
                # Check if user wants to enter more URLs
                print("(Enter more URLs or press Enter on empty line to process)")
                while True:
                    line = input().strip()
                    if not line:
                        break
                    if line.lower() in ['quit', 'exit', 'q']:
                        print("Goodbye!")
                        return
                    urls.append(line)
                
                # Validate URLs
                valid_urls = []
                for url in urls:
                    if not url.startswith(('http://', 'https://')):
                        print(f"Skipping invalid URL: {url}")
                        continue
                    valid_urls.append(url)
                
                if not valid_urls:
                    print("No valid URLs to process.")
                    continue
                
                # Process URLs
                if len(valid_urls) == 1:
                    self.process_url(valid_urls[0])
                else:
                    self.process_batch(valid_urls)
                
                print()  # Empty line before next prompt

            except KeyboardInterrupt:
                print("\n\nInterrupted. Goodbye!")
                break
            except Exception as e:
                print(f"Unexpected error: {e}", file=sys.stderr)
                continue

    def run(self, urls_file: Optional[str] = None):
        """Main program loop.
        
        Args:
            urls_file: Optional path to a file containing URLs (one per line)
        """
        print(f"Fuji Recipe URL Downloader v{VERSION}\n")

        # Load or create configuration
        if not self.load_or_create_config():
            print("Failed to load configuration. Exiting.", file=sys.stderr)
            sys.exit(1)

        # Initialize Claude client
        if not self.initialize_client():
            print("Failed to initialize Claude client. Exiting.", file=sys.stderr)
            sys.exit(1)

        # Load XSD schema
        if not self.load_xsd_schema():
            print("Failed to load XSD schema. Exiting.", file=sys.stderr)
            sys.exit(1)

        print(f"Recipe folder: {self.config['recipe_folder']}\n")

        # Process URLs from file if provided
        if urls_file:
            print(f"Reading URLs from: {urls_file}")
            urls = self.read_urls_from_file(urls_file)
            
            if not urls:
                print("No valid URLs found in file.", file=sys.stderr)
                sys.exit(1)
            
            # Validate URLs
            valid_urls = []
            for url in urls:
                if not url.startswith(('http://', 'https://')):
                    print(f"Skipping invalid URL: {url}")
                    continue
                valid_urls.append(url)
            
            if not valid_urls:
                print("No valid URLs to process.", file=sys.stderr)
                sys.exit(1)
            
            self.process_batch(valid_urls)
        else:
            # Interactive mode
            self.run_interactive()


def main():
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Download recipe content from URLs and convert to Fuji FP1 XML format",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive mode (single or multiple URLs)
  %(prog)s
  
  # Batch mode from file
  %(prog)s --file urls.txt
  %(prog)s -f recipes.txt
  
File format:
  - One URL per line
  - Lines starting with # are ignored (comments)
  - Empty lines are ignored
        """
    )
    
    parser.add_argument(
        '-f', '--file',
        metavar='FILE',
        help='Path to file containing URLs (one per line)'
    )
    
    parser.add_argument(
        '--version',
        action='version',
        version=f'%(prog)s {VERSION}'
    )
    
    args = parser.parse_args()
    
    downloader = RecipeDownloader()
    downloader.run(urls_file=args.file)


if __name__ == "__main__":
    main()

