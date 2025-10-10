#!/usr/bin/env python3
"""
Bulk XML Validator with XSD Schema
Scans directories recursively for XML files and validates them against an XSD schema.
"""

import argparse
import sys
from pathlib import Path
from typing import Tuple, List
from dataclasses import dataclass

# Color codes for terminal output
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    RESET = '\033[0m'
    DIM = '\033[2m'

@dataclass
class ValidationResult:
    file_path: Path
    is_valid: bool
    error_message: str = ""
    
    @property
    def relative_path_str(self):
        try:
            return str(self.file_path.relative_to(Path.cwd()))
        except ValueError:
            return str(self.file_path)


def validate_xml_file(xml_path: Path, xsd_schema) -> ValidationResult:
    """
    Validate a single XML file against the XSD schema.
    
    Args:
        xml_path: Path to the XML file
        xsd_schema: Compiled lxml XMLSchema object
        
    Returns:
        ValidationResult object with validation status and error message
    """
    from lxml import etree
    
    try:
        # Parse the XML file
        with open(xml_path, 'r', encoding='utf-8') as f:
            xml_doc = etree.parse(f)
        
        # Validate against schema
        try:
            xsd_schema.assertValid(xml_doc)
            return ValidationResult(xml_path, True)
        except etree.DocumentInvalid as e:
            # Get detailed error information
            error_lines = []
            for error in xsd_schema.error_log:
                error_lines.append(f"Line {error.line}: {error.message}")
            error_message = "; ".join(error_lines) if error_lines else str(e)
            return ValidationResult(xml_path, False, error_message)
            
    except etree.XMLSyntaxError as e:
        return ValidationResult(xml_path, False, f"XML Syntax Error: {e}")
    except Exception as e:
        return ValidationResult(xml_path, False, f"Unexpected error: {e}")


def find_xml_files(directory: Path, extensions: List[str] = None) -> List[Path]:
    """
    Recursively find all XML files in the directory.
    
    Args:
        directory: Directory to search
        extensions: List of file extensions to search for (e.g., ['.xml', '.FP1'])
                   If None, searches for common XML extensions
        
    Returns:
        List of Path objects for found XML files
    """
    if extensions is None:
        extensions = ['.xml', '.XML', '.FP1', '.fp1']
    
    xml_files = []
    
    for ext in extensions:
        # Use rglob for recursive search
        xml_files.extend(directory.rglob(f'*{ext}'))
    
    # Sort for consistent output
    return sorted(xml_files)


def load_xsd_schema(xsd_path: Path):
    """
    Load and compile the XSD schema.
    
    Args:
        xsd_path: Path to the XSD schema file
        
    Returns:
        Compiled XMLSchema object
        
    Raises:
        Exception if schema cannot be loaded
    """
    try:
        from lxml import etree
    except ImportError:
        print(f"{Colors.RED}Error: lxml is not installed{Colors.RESET}")
        print("Install it with: pip install lxml")
        sys.exit(1)
    
    if not xsd_path.exists():
        print(f"{Colors.RED}Error: XSD schema not found at {xsd_path}{Colors.RESET}")
        sys.exit(1)
    
    try:
        with open(xsd_path, 'r', encoding='utf-8') as f:
            schema_doc = etree.parse(f)
        return etree.XMLSchema(schema_doc)
    except Exception as e:
        print(f"{Colors.RED}Error loading XSD schema: {e}{Colors.RESET}")
        sys.exit(1)


def print_header(title: str):
    """Print a formatted header."""
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'=' * 70}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{title:^70}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'=' * 70}{Colors.RESET}\n")


def print_summary(results: List[ValidationResult]):
    """Print validation summary statistics."""
    valid_count = sum(1 for r in results if r.is_valid)
    invalid_count = len(results) - valid_count
    
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'─' * 70}{Colors.RESET}")
    print(f"{Colors.BOLD}Validation Summary:{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'─' * 70}{Colors.RESET}")
    print(f"  Total files:    {Colors.BOLD}{len(results)}{Colors.RESET}")
    print(f"  Valid:          {Colors.GREEN}{Colors.BOLD}{valid_count}{Colors.RESET} {Colors.GREEN}✓{Colors.RESET}")
    print(f"  Invalid:        {Colors.RED}{Colors.BOLD}{invalid_count}{Colors.RESET} {Colors.RED}✗{Colors.RESET}")
    
    if len(results) > 0:
        success_rate = (valid_count / len(results)) * 100
        color = Colors.GREEN if success_rate == 100 else (Colors.YELLOW if success_rate >= 50 else Colors.RED)
        print(f"  Success rate:   {color}{Colors.BOLD}{success_rate:.1f}%{Colors.RESET}")
    
    print(f"{Colors.BOLD}{Colors.CYAN}{'─' * 70}{Colors.RESET}\n")


def main():
    parser = argparse.ArgumentParser(
        description='Bulk validate XML files against an XSD schema',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                                       # Validate all XML files in current directory
  %(prog)s /path/to/xml/files                    # Validate all XML files in directory
  %(prog)s recipe.FP1                            # Validate a single file
  %(prog)s ./recipes --xsd fuji-recipe.xsd       # Specify custom XSD schema
  %(prog)s ./data --ext .xml .fp1                # Search for specific extensions
  %(prog)s ./recipes --verbose                   # Show detailed error messages
  %(prog)s ./recipes --only-invalid              # Only show invalid files
        """
    )
    
    parser.add_argument(
        'path',
        type=str,
        nargs='?',
        default='.',
        help='File or directory to validate (default: current directory)'
    )
    
    parser.add_argument(
        '--xsd',
        type=str,
        help='Path to XSD schema file (default: fuji-recipe.xsd in script directory)'
    )
    
    parser.add_argument(
        '--ext',
        nargs='+',
        default=['.xml', '.XML', '.FP1', '.fp1'],
        help='File extensions to search for (default: .xml .XML .FP1 .fp1)'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed error messages for invalid files'
    )
    
    parser.add_argument(
        '--only-invalid',
        action='store_true',
        help='Only display invalid files'
    )
    
    parser.add_argument(
        '--no-color',
        action='store_true',
        help='Disable colored output'
    )
    
    args = parser.parse_args()
    
    # Disable colors if requested
    if args.no_color:
        for attr in dir(Colors):
            if not attr.startswith('_'):
                setattr(Colors, attr, '')
    
    # Get paths
    target_path = Path(args.path).resolve()
    
    if not target_path.exists():
        print(f"{Colors.RED}Error: Path not found: {target_path}{Colors.RESET}")
        sys.exit(1)
    
    # Check if it's a file or directory
    is_single_file = target_path.is_file()
    
    # Determine XSD schema path
    if args.xsd:
        xsd_path = Path(args.xsd).resolve()
    else:
        # Default to fuji-recipe.xsd in script directory
        xsd_path = Path(__file__).parent / 'fuji-recipe.xsd'
    
    # Print header
    print_header("XML Schema Validator")
    
    print(f"{Colors.BOLD}Configuration:{Colors.RESET}")
    if is_single_file:
        print(f"  Target file:      {Colors.CYAN}{target_path}{Colors.RESET}")
    else:
        print(f"  Search directory: {Colors.CYAN}{target_path}{Colors.RESET}")
        print(f"  Extensions:       {Colors.CYAN}{', '.join(args.ext)}{Colors.RESET}")
    print(f"  XSD schema:       {Colors.CYAN}{xsd_path}{Colors.RESET}")
    print()
    
    # Load XSD schema
    print(f"{Colors.YELLOW}Loading XSD schema...{Colors.RESET}")
    xsd_schema = load_xsd_schema(xsd_path)
    print(f"{Colors.GREEN}✓ Schema loaded successfully{Colors.RESET}\n")
    
    # Find XML files
    if is_single_file:
        xml_files = [target_path]
        print(f"{Colors.GREEN}✓ Validating single file{Colors.RESET}\n")
    else:
        print(f"{Colors.YELLOW}Scanning for XML files...{Colors.RESET}")
        xml_files = find_xml_files(target_path, args.ext)
        
        if not xml_files:
            print(f"{Colors.YELLOW}No XML files found in {target_path}{Colors.RESET}")
            sys.exit(0)
        
        print(f"{Colors.GREEN}✓ Found {len(xml_files)} XML file(s){Colors.RESET}\n")
    
    # Validate files
    print(f"{Colors.BOLD}Validating files...{Colors.RESET}\n")
    
    results = []
    for xml_file in xml_files:
        result = validate_xml_file(xml_file, xsd_schema)
        results.append(result)
        
        # Skip valid files if --only-invalid is set
        if args.only_invalid and result.is_valid:
            continue
        
        # Print result
        if result.is_valid:
            print(f"  {Colors.GREEN}✓{Colors.RESET} {Colors.DIM}{result.relative_path_str}{Colors.RESET}")
        else:
            print(f"  {Colors.RED}✗{Colors.RESET} {Colors.BOLD}{result.relative_path_str}{Colors.RESET}")
            
            if args.verbose and result.error_message:
                # Indent error message
                for line in result.error_message.split('; '):
                    print(f"    {Colors.RED}↳{Colors.RESET} {Colors.DIM}{line}{Colors.RESET}")
    
    # Print summary
    print_summary(results)
    
    # Exit with error code if any files are invalid
    invalid_count = sum(1 for r in results if not r.is_valid)
    sys.exit(1 if invalid_count > 0 else 0)


if __name__ == '__main__':
    main()

