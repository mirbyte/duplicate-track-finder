import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import re
from pathlib import Path
from collections import defaultdict
from difflib import SequenceMatcher
import threading
import platform
from datetime import datetime
from colorama import init, Fore, Style
from typing import Dict, List, Tuple, Optional, Set
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing
from functools import partial
import unicodedata

# github/mirbyte
# v0.1

# Initialize colorama for Windows compatibility
init()

# For audio metadata - install with: pip install tinytag
try:
    from tinytag import TinyTag
    METADATA_AVAILABLE = True
except ImportError:
    METADATA_AVAILABLE = False
    print(f"{Fore.YELLOW}Warning: tinytag not installed. Install with 'pip install tinytag' for metadata support.{Style.RESET_ALL}")

class MetadataHandler:
    """Handles all metadata extraction and processing operations"""
    
    @staticmethod
    def safe_path(path_str: str) -> Path:
        """Handle Windows long paths and special characters with improved error handling"""
        try:
            path = Path(path_str)
            if platform.system() == 'Windows':
                abs_path = path.resolve()
                abs_path_str = str(abs_path)
                if len(abs_path_str) >= 260 and not abs_path_str.startswith('\\\\?\\'):
                    abs_path_str = '\\\\?\\' + abs_path_str
                return Path(abs_path_str)
            return path
        except (OSError, ValueError) as e:
            print(f"{Fore.YELLOW}Warning: Path conversion failed for {path_str}: {e}{Style.RESET_ALL}")
            return Path(path_str)
    
    @staticmethod
    def get_audio_quality_indicator(file_path: Path) -> str:
        """Determine if audio format is lossy or lossless based on file extension"""
        ext = file_path.suffix.lower()
        lossless_exts = {'.flac', '.wav', '.aiff', '.dsd', '.ape'}
        return 'Lossless' if ext in lossless_exts else 'Lossy'
    
    @staticmethod
    def format_timestamp(timestamp: float) -> str:
        """Format timestamp to readable date string with better error handling"""
        try:
            return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
        except (OSError, ValueError, OverflowError):
            return 'Unknown'
    
    @staticmethod
    def normalize_single_artist_name(name: str) -> str:
        """Normalize a single artist name for consistent comparison"""
        if not name:
            return ''
        
        # Strip all whitespace first
        name = name.strip()
        
        # Convert to lowercase EARLY to handle case sensitivity
        name = name.lower()
        
        # Normalize unicode characters - use NFKC for better compatibility
        # Then try to convert to ASCII to handle accented characters
        name = unicodedata.normalize('NFKC', name)
        try:
            # Try to encode to ASCII, removing accents
            name = name.encode('ascii', 'ignore').decode('ascii')
        except:
            pass  # If it fails, keep the NFKC normalized version
        
        # Remove common prefixes/suffixes from featuring credits
        name = re.sub(r'^(feat\.?|ft\.?|featuring)\s+', '', name, flags=re.IGNORECASE)
        name = re.sub(r'\s+(feat\.?|ft\.?|featuring).*$', '', name, flags=re.IGNORECASE)
        
        # Remove extra whitespace and normalize
        name = re.sub(r'\s+', ' ', name).strip()
        
        # Remove common punctuation that might cause issues
        name = re.sub(r'["""\'\'`]', '', name)
        
        # Remove periods and hyphens that might differ between metadata
        name = name.replace('.', '').replace('-', ' ')
        name = re.sub(r'\s+', ' ', name).strip()
        
        return name
    
    @staticmethod
    def normalize_artists(artist_str: str) -> set:
        """Normalization of contributing artists string to a set of artist names"""
        if not artist_str:
            return set()
        
        # Debug: show original input
        print(f"{Fore.CYAN}Normalizing artists: '{artist_str}'{Style.RESET_ALL}")
        
        # Step 1: Convert to lowercase IMMEDIATELY to handle case sensitivity early
        cleaned = artist_str.lower().strip()
        
        # Step 2: Normalize unicode early - use NFKC for better compatibility
        cleaned = unicodedata.normalize('NFKC', cleaned)
        try:
            # Try to convert to ASCII to handle accented characters uniformly
            cleaned = cleaned.encode('ascii', 'ignore').decode('ascii')
        except:
            pass
        
        # Step 3: Remove trailing delimiters (semicolons, commas at the end)
        cleaned = re.sub(r'[;,\s]+$', '', cleaned)
        
        # Step 4: Handle BOTH semicolons AND commas as primary delimiters
        # Replace semicolons with commas first to standardize
        cleaned = cleaned.replace(';', ',')
        
        # Step 5: Handle various other delimiters - replace with standardized comma
        # Handle ampersands, plus signs, forward/back slashes, pipes
        cleaned = re.sub(r'\s*[&+/\\|]\s*', ',', cleaned)
        
        # Step 6: Handle word-based delimiters (and, feat, ft, vs, x, with)
        cleaned = re.sub(r'\s+(and|feat\.?|ft\.?|vs\.?|versus|x|with)\s+', ',', cleaned, flags=re.IGNORECASE)
        
        # Step 7: Clean up multiple consecutive commas and whitespace
        cleaned = re.sub(r',+', ',', cleaned)  # Multiple commas -> single comma
        cleaned = re.sub(r'\s*,\s*', ',', cleaned)  # Whitespace around commas
        
        # Step 8: Remove leading/trailing commas
        cleaned = cleaned.strip(',').strip()
        
        # Debug: show after initial cleaning
        print(f"{Fore.CYAN}After cleaning: '{cleaned}'{Style.RESET_ALL}")
        
        # Step 9: Split by comma and normalize each artist name individually
        artists = set()
        if cleaned:
            for artist in cleaned.split(','):
                # Don't call normalize_single_artist_name since we already did lowercase
                # Just do the additional cleaning specific to single names
                artist = artist.strip()
                if not artist:
                    continue
                
                # Remove featuring credits
                artist = re.sub(r'^(feat\.?|ft\.?|featuring)\s+', '', artist, flags=re.IGNORECASE)
                artist = re.sub(r'\s+(feat\.?|ft\.?|featuring).*$', '', artist, flags=re.IGNORECASE)
                
                # Remove parenthetical suffixes (country codes, etc.)
                artist = re.sub(r'\s*\([^)]*\)', '', artist)
                
                # Remove extra whitespace
                artist = re.sub(r'\s+', ' ', artist).strip()
                
                # Remove punctuation
                artist = re.sub(r'["""\'\'`]', '', artist)
                artist = artist.replace('.', '').replace('-', ' ')
                artist = re.sub(r'\s+', ' ', artist).strip()
                
                if artist:  # Only add non-empty names
                    artists.add(artist)
        
        # Debug: show final result
        print(f"{Fore.GREEN}Normalized artists: {sorted(artists)}{Style.RESET_ALL}")
        
        return artists
    
    @staticmethod
    def get_title_first_word(title: str) -> str:
        """Get the first significant word from the title, ignoring common articles"""
        if not title:
            return ''
        
        # Normalize unicode and strip
        title = unicodedata.normalize('NFKD', title).strip()
        
        # Remove common prefixes
        title = re.sub(r'^(the|a|an)\s+', '', title, flags=re.IGNORECASE)
        
        # Get first word and normalize
        words = title.strip().split()
        if words:
            first_word = words[0].lower()
            # Remove punctuation from first word
            first_word = re.sub(r'[^\w\s]', '', first_word)
            return first_word
        return ''
    
    @staticmethod
    def extract_comprehensive_artists(tag) -> str:
        """Extract ONLY the primary artist field for duplicate detection"""
    
        # Priority 1: Primary artist field (this is the "Contributing artists" in file properties)
        if hasattr(tag, 'artist') and tag.artist:
            artist_str = str(tag.artist).strip()
            if artist_str:
                print(f"{Fore.CYAN}Found artist field: '{artist_str}'{Style.RESET_ALL}")
                # Normalize this field
                normalized = MetadataHandler.normalize_artists(artist_str)
                if normalized:
                    # Return as a comma-separated string (already normalized)
                    result = ', '.join(sorted(normalized))
                    print(f"{Fore.GREEN}Using artist field: '{result}'{Style.RESET_ALL}")
                    return result
    
        # Priority 2: Album artist field (only if artist field is empty)
        if hasattr(tag, 'albumartist') and tag.albumartist:
            albumartist_str = str(tag.albumartist).strip()
            if albumartist_str:
                print(f"{Fore.YELLOW}Artist field empty, using albumartist: '{albumartist_str}'{Style.RESET_ALL}")
                normalized = MetadataHandler.normalize_artists(albumartist_str)
                if normalized:
                    result = ', '.join(sorted(normalized))
                    print(f"{Fore.GREEN}Using albumartist field: '{result}'{Style.RESET_ALL}")
                    return result
    
        # Priority 3: Composer field (only if both artist and albumartist are empty)
        if hasattr(tag, 'composer') and tag.composer:
            composer_str = str(tag.composer).strip()
            if composer_str:
                print(f"{Fore.YELLOW}Artist and albumartist empty, using composer: '{composer_str}'{Style.RESET_ALL}")
                normalized = MetadataHandler.normalize_artists(composer_str)
                if normalized:
                    result = ', '.join(sorted(normalized))
                    print(f"{Fore.GREEN}Using composer field: '{result}'{Style.RESET_ALL}")
                    return result
    
        print(f"{Fore.RED}No artist information found in any field{Style.RESET_ALL}")
        return ''

    
    @staticmethod
    def extract_file_metadata(file_path_str: str) -> Dict:
        """Extract comprehensive file metadata - designed for multiprocessing"""
        try:
            file_path = MetadataHandler.safe_path(file_path_str)
            metadata = {
                'file_path': file_path_str,
                'filename': file_path.name,
                'size_mb': 0,
                'size_bytes': 0,
                'duration_formatted': "",
                'quality': MetadataHandler.get_audio_quality_indicator(file_path),
                'modified_date': 'Unknown',
                'created_date': 'Unknown',
                'title': '',
                'contributing_artists': '',  # This is what we use for comparison
                'album_artist': '',  # Separate field for display/comparison
                'raw_artists': '',  # Original raw artist string for debugging
                'normalized_artists_debug': '',  # Debugging info
                'success': True
            }
            
            # Get basic file information
            try:
                stat = os.stat(file_path)
                metadata['size_bytes'] = stat.st_size
                metadata['size_mb'] = round(stat.st_size / (1024 * 1024))
                metadata['modified'] = stat.st_mtime
                metadata['modified_date'] = MetadataHandler.format_timestamp(stat.st_mtime)
                
                if platform.system() == 'Windows':
                    metadata['created'] = stat.st_ctime
                    metadata['created_date'] = MetadataHandler.format_timestamp(stat.st_ctime)
                else:
                    if hasattr(stat, 'st_birthtime'):
                        metadata['created'] = stat.st_birthtime
                        metadata['created_date'] = MetadataHandler.format_timestamp(stat.st_birthtime)
                    else:
                        metadata['created'] = stat.st_mtime
                        metadata['created_date'] = metadata['modified_date']
            except (PermissionError, OSError) as e:
                metadata['file_error'] = str(e)
                metadata['success'] = False
            
            # Get audio metadata if available
            if METADATA_AVAILABLE and metadata['success']:
                try:
                    tag = TinyTag.get(str(file_path))
                    
                    # Extract comprehensive artist information
                    comprehensive_artists = MetadataHandler.extract_comprehensive_artists(tag)
                    
                    # Store raw artists for debugging
                    metadata['raw_artists'] = comprehensive_artists
                    
                    # Normalize the artists and store debug info
                    normalized_artists_set = MetadataHandler.normalize_artists(comprehensive_artists)
                    metadata['normalized_artists_debug'] = ', '.join(sorted(normalized_artists_set))
                    
                    metadata.update({
                        'title': tag.title or '',
                        'contributing_artists': comprehensive_artists,  # Use comprehensive extraction
                        'album_artist': tag.albumartist or '',  # Album artist (separate field)
                        'album': tag.album or '',
                        'year': tag.year or '',
                        'genre': tag.genre or '',
                        'duration': tag.duration or 0,
                        'bitrate': round(tag.bitrate) if tag.bitrate else 0,
                        'samplerate': tag.samplerate or 0,
                        'channels': tag.channels or 0
                    })
                    
                    # Keep 'artist' field for backward compatibility in UI display
                    metadata['artist'] = metadata['contributing_artists']
                    
                    if metadata['duration']:
                        minutes = int(metadata['duration'] // 60)
                        seconds = int(metadata['duration'] % 60)
                        metadata['duration_formatted'] = f"{minutes}:{seconds:02d}"
                        
                except Exception as e:
                    metadata['metadata_error'] = str(e)
                    
        except Exception as e:
            metadata = {
                'file_path': file_path_str,
                'filename': Path(file_path_str).name,
                'error': str(e),
                'success': False
            }
        
        return metadata

class FileOperations:
    """Handles file system operations and duplicate detection logic"""
    
    def __init__(self):
        self.extensions = {'.flac', '.mp3', '.wav', '.m4a', '.ogg', '.aac', '.wma', '.opus', '.aiff', '.ape'}
    
    def find_audio_files(self, directory: str) -> List[str]:
        """Find all audio files in directory and subdirectories"""
        audio_files = []
        base_path = Path(directory)
        
        try:
            for file_path in base_path.rglob('*'):
                if file_path.is_file() and file_path.suffix.lower() in self.extensions:
                    audio_files.append(str(file_path))
        except PermissionError:
            print(f"{Fore.RED}Permission denied accessing directory: {directory}{Style.RESET_ALL}")
        
        return audio_files
    
    def process_files_parallel(self, file_paths: List[str], progress_callback=None, max_workers=None) -> List[Dict]:
        """Process file metadata extraction using multiprocessing"""
        if not file_paths:
            return []
        
        if max_workers is None:
            max_workers = min(multiprocessing.cpu_count(), len(file_paths))
        
        metadata_list = []
        completed = 0
        
        try:
            with ProcessPoolExecutor(max_workers=max_workers) as executor:
                # Submit all tasks
                future_to_path = {
                    executor.submit(MetadataHandler.extract_file_metadata, path): path
                    for path in file_paths
                }
                
                # Process completed tasks
                for future in as_completed(future_to_path):
                    path = future_to_path[future]
                    try:
                        metadata = future.result()
                        metadata_list.append(metadata)
                    except Exception as e:
                        print(f"{Fore.RED}Error processing {Path(path).name}: {e}{Style.RESET_ALL}")
                        # Add minimal metadata for failed files
                        metadata_list.append({
                            'file_path': path,
                            'filename': Path(path).name,
                            'error': str(e),
                            'success': False
                        })
                    
                    completed += 1
                    if progress_callback:
                        progress_callback(completed, len(file_paths))
        
        except Exception as e:
            print(f"{Fore.RED}Multiprocessing error: {e}{Style.RESET_ALL}")
            # Fallback to sequential processing
            return self._process_files_sequential(file_paths, progress_callback)
        
        return metadata_list
    
    def _process_files_sequential(self, file_paths: List[str], progress_callback=None) -> List[Dict]:
        """Fallback sequential processing"""
        metadata_list = []
        for i, path in enumerate(file_paths):
            metadata = MetadataHandler.extract_file_metadata(path)
            metadata_list.append(metadata)
            if progress_callback:
                progress_callback(i + 1, len(file_paths))
        return metadata_list
    
    @staticmethod
    def create_backup_list(files_to_delete: Set[str], directory: str) -> Optional[str]:
        """Create a backup list of files to be deleted"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_filename = f"deleted_files_backup_{timestamp}.txt"
            backup_path = Path(directory) / backup_filename
            
            with open(backup_path, 'w', encoding='utf-8') as f:
                f.write(f"Audio Duplicate Detector - Deleted Files Backup\n")
                f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Directory: {directory}\n")
                f.write("=" * 60 + "\n\n")
                
                for file_path in sorted(files_to_delete):
                    f.write(f"{file_path}\n")
            
            return str(backup_path)
        except Exception as e:
            print(f"{Fore.YELLOW}Could not create backup list: {str(e)}{Style.RESET_ALL}")
            return None
    
    @staticmethod
    def delete_files(files_to_delete: Set[str]) -> Tuple[int, List[str]]:
        """Delete files and return success count and failed deletions"""
        deleted_count = 0
        failed_deletions = []
        
        for file_path in files_to_delete:
            try:
                safe_file_path = MetadataHandler.safe_path(file_path)
                os.remove(safe_file_path)
                deleted_count += 1
            except PermissionError:
                failed_deletions.append(f"{Path(file_path).name}: Permission denied")
            except FileNotFoundError:
                failed_deletions.append(f"{Path(file_path).name}: File not found")
            except Exception as e:
                failed_deletions.append(f"{Path(file_path).name}: {str(e)}")
        
        return deleted_count, failed_deletions

class DuplicateDetector:
    """Core duplicate detection logic based on Contributing artists"""
    
    def __init__(self):
        self.metadata_handler = MetadataHandler()
    
    def group_by_metadata(self, files_metadata: List[Dict]) -> Dict:
        """Group files by base title similarity and artist overlap"""
    
        # Extract base title helper
        def extract_base_title(title: str) -> str:
            """Extract base title by removing mix/version info"""
            if not title:
                return ''
        
            title = title.lower().strip()
        
            # Remove version info in parentheses/brackets
            title = re.sub(r'\s*[\(\[].*?[\)\]]', '', title)
        
            # Remove version suffixes after dashes
            title = re.sub(r'\s*[-–—]\s*(extended|radio|club|original|vocal|instrumental|acoustic|remix|mix|edit|version|dub).*$', '', title, flags=re.IGNORECASE)
        
            # Clean whitespace
            title = re.sub(r'\s+', ' ', title).strip()
        
            return title
    
        # First pass: collect all file info
        file_info_list = []
    
        for meta in files_metadata:
            if not meta.get('success', False):
                continue
        
            title = meta.get('title', '')
            contributing_artists_str = meta.get('contributing_artists', '')
            file_path = meta.get('file_path', '')
        
            if not title or not file_path:
                continue
        
            base_title = extract_base_title(title)
            contributing_artists = MetadataHandler.normalize_artists(contributing_artists_str) if contributing_artists_str else set()
        
            if base_title and contributing_artists:
                file_info_list.append({
                    'file_path': file_path,
                    'base_title': base_title,
                    'artists': contributing_artists,
                    'grouped': False
                })
            
                print(f"{Fore.MAGENTA}File: {Path(file_path).name}{Style.RESET_ALL}")
                print(f"  Base title: '{base_title}'")
                print(f"  Artists: {sorted(contributing_artists)}\n")
    
        # Second pass: group similar files
        groups = []
    
        for i, file1 in enumerate(file_info_list):
            if file1['grouped']:
                continue
        
            current_group = [file1]
            file1['grouped'] = True
        
            for j in range(i + 1, len(file_info_list)):
                file2 = file_info_list[j]
            
                if file2['grouped']:
                    continue
            
                # Check if titles match (exact or very close)
                titles_match = file1['base_title'] == file2['base_title']
            
                # Check if artists have ANY overlap (at least 1 artist in common)
                artists_overlap = len(file1['artists'] & file2['artists']) > 0
            
                # Also check if one artist set is a subset of the other
                artists_subset = file1['artists'].issubset(file2['artists']) or file2['artists'].issubset(file1['artists'])
            
                if titles_match and (artists_overlap or artists_subset):
                    current_group.append(file2)
                    file2['grouped'] = True
                
                    print(f"{Fore.GREEN}✓ MATCH FOUND!{Style.RESET_ALL}")
                    print(f"  '{file1['base_title']}' == '{file2['base_title']}'")
                    print(f"  Common artists: {sorted(file1['artists'] & file2['artists'])}")
                    print(f"  File1 artists: {sorted(file1['artists'])}")
                    print(f"  File2 artists: {sorted(file2['artists'])}\n")
        
            # Only create group if 2+ files
            if len(current_group) >= 2:
                groups.append(current_group)
    
        # Convert to expected format
        result = {}
        for idx, group in enumerate(groups, 1):
            first_file = group[0]
            artists_str = ', '.join(sorted(first_file['artists']))
            group_name = f"{first_file['base_title'].title()} - {artists_str}"
        
            result[group_name] = [file['file_path'] for file in group]
    
        return result
        
    
    def get_metadata_differences(self, selected_file_path: str, group_files: List[str]) -> List[Tuple[str, Optional[str]]]:
        """Compare metadata between files in the same duplicate group"""
        if not METADATA_AVAILABLE:
            return [("Audio metadata not available (Install tinytag: pip install tinytag)", None)]
        
        all_metadata = []
        for file_path in group_files:
            metadata = MetadataHandler.extract_file_metadata(file_path)
            all_metadata.append(metadata)
        
        selected_metadata = None
        selected_index = -1
        for i, metadata in enumerate(all_metadata):
            if metadata['file_path'] == selected_file_path:
                selected_metadata = metadata
                selected_index = i
                break
        
        if not selected_metadata:
            return [("Could not find metadata for selected file", None)]
        
        # Updated fields to include debug information
        compare_fields = ['title', 'contributing_artists', 'album_artist', 'raw_artists', 'normalized_artists_debug',
                         'year',
                         'quality', 'modified_date', 'created_date']
                         
        # old compare_fields = ['title', 'contributing_artists', 'album_artist', 'raw_artists', 'normalized_artists_debug',
                        # 'album', 'year', 'genre', 'duration_formatted', 'bitrate', 'samplerate', 'channels',
                        # 'quality', 'modified_date', 'created_date']
        
        differing_fields = {}
        for field in compare_fields:
            values = set()
            for metadata in all_metadata:
                value = metadata.get(field, '')
                str_value = str(value) if value not in [None, '', 0, 'Unknown'] else ''
                values.add(str_value)
            
            if len(values) > 1:
                differing_fields[field] = True
        
        if not differing_fields:
            return [(f"Selected: {Path(selected_file_path).name}\n\n", None),
                   ("✓ No metadata differences found\n", None),
                   ("All files in this group have identical metadata.", None)]
        
        result = [(f"Selected: {Path(selected_file_path).name}\n", None),
                 ("=" * 70 + "\n\n", None)]
        
        # Updated field labels to include debug information
        field_labels = {
            'title': 'Title',
            'contributing_artists': 'Contributing Artists',
            'album_artist': 'Album Artist',
            'raw_artists': 'Raw Artists (Before Normalization)',
            'normalized_artists_debug': 'Normalized Artists (After Processing)',
            'album': 'Album',
            'year': 'Year',
            'genre': 'Genre',
            'duration_formatted': 'Duration',
            'bitrate': 'Bitrate',
            'samplerate': 'Sample Rate',
            'channels': 'Channels',
            'size_mb': 'Size (MB)',
            'quality': 'Quality',
            'modified_date': 'Modified Date',
            'created_date': 'Created Date'
        }
        
        for field in differing_fields.keys():
            if field not in field_labels:
                continue
            
            label = field_labels[field]
            result.append((f"{label}:\n", None))
            
            for i, metadata in enumerate(all_metadata):
                filename = Path(metadata['file_path']).name
                display_name = filename
                value = metadata.get(field, '')
                display_value = str(value) if value not in [None, '', 0, 'Unknown'] else 'Unknown'
                
                prefix = "► " if i == selected_index else "  "
                tag = 'title_bold' if field == 'title' else None
                result.append((f"{prefix}{display_name} = {display_value}\n", tag))
            
            result.append(("\n", None))
        
        return result

class AudioDuplicateDetectorUI:
    """Main UI class handling all interface operations"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("github/mirbyte")
        self.root.geometry("2500x1500")
        
        # Initialize core components
        self.file_ops = FileOperations()
        self.duplicate_detector = DuplicateDetector()
        
        # Set current directory as default
        self.current_directory = os.getcwd()
        self.duplicate_groups: Dict[str, List[str]] = {}
        self.selected_files: Set[str] = set()
        self.item_data: Dict[str, Dict] = {}
        
        # Progress tracking
        self.total_files = 0
        self.processed_files = 0
        self.scan_cancelled = False
        
        self.setup_ui()
        self.setup_keyboard_shortcuts()
    
    def setup_keyboard_shortcuts(self):
        """Setup keyboard shortcuts for common operations"""
        self.root.bind('<Control-a>', lambda e: self.select_all())
        self.root.bind('<Control-A>', lambda e: self.select_all())
        self.root.bind('<Delete>', lambda e: self.delete_selected())
        self.root.focus_set()
    
    def setup_ui(self):
        """Setup the main user interface with improved styling"""
        style = ttk.Style()
        style.configure("Treeview", rowheight=25)
        style.configure("Treeview.Heading", font=('TkDefaultFont', 9, 'bold'))
        
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(2, weight=1)
        
        # Directory selection frame
        dir_frame = ttk.Frame(main_frame)
        dir_frame.grid(row=0, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 10))
        dir_frame.columnconfigure(1, weight=1)
        
        ttk.Label(dir_frame, text="Directory:").grid(row=0, column=0, padx=(0, 10))
        self.dir_var = tk.StringVar(value=self.current_directory)
        ttk.Entry(dir_frame, textvariable=self.dir_var, state="readonly").grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 10))
        ttk.Button(dir_frame, text="Browse", command=self.browse_directory).grid(row=0, column=2, padx=(0, 10))
        self.scan_button = ttk.Button(dir_frame, text="Scan for Duplicates", command=self.scan_duplicates)
        self.scan_button.grid(row=0, column=3)
        
        # Progress bar and label
        progress_frame = ttk.Frame(main_frame)
        progress_frame.grid(row=1, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 10))
        progress_frame.columnconfigure(0, weight=1)
        
        self.progress = ttk.Progressbar(progress_frame, mode='determinate')
        self.progress.grid(row=0, column=0, sticky=(tk.W, tk.E))
        self.progress_label = ttk.Label(progress_frame, text="")
        self.progress_label.grid(row=1, column=0, pady=(2, 0))
        
        # Paned window for split view
        paned = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        paned.grid(row=2, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Left panel - Duplicate groups
        left_frame = ttk.Frame(paned)
        paned.add(left_frame, weight=4)
        
        ttk.Label(left_frame, text="Duplicate Groups", font=('TkDefaultFont', 11, 'bold')).pack(pady=(0, 5))
        
        # Right panel - Metadata differences
        right_frame = ttk.Frame(paned)
        paned.add(right_frame, weight=1)
        
        ttk.Label(right_frame, text="Metadata Differences", font=('TkDefaultFont', 11, 'bold')).pack(pady=(0, 5))
        
        # Treeview for duplicates
        tree_frame = ttk.Frame(left_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        
        self.tree = ttk.Treeview(tree_frame, columns=('title', 'artist', 'length', 'size', 'quality', 'select'),
                                show='tree headings', selectmode='extended')
        
        # Columns
        self.tree.heading('#0', text='File Name')
        self.tree.heading('title', text='Title')
        self.tree.heading('artist', text='Contributing Artists')
        self.tree.heading('length', text='Length')
        self.tree.heading('size', text='Size (MB)')
        self.tree.heading('quality', text='Quality')
        self.tree.heading('select', text='Delete?')

        # Configure column widths
        self.tree.column('#0', width=300, minwidth=200)
        self.tree.column('title', width=200, minwidth=120)
        self.tree.column('artist', width=300, minwidth=140)
        self.tree.column('length', width=120, minwidth=40, anchor='center', stretch=False)
        self.tree.column('size', width=120, minwidth=40, anchor='center', stretch=False)
        self.tree.column('quality', width=150, minwidth=40, anchor='center', stretch=False)
        self.tree.column('select', width=100, minwidth=40, anchor='center', stretch=False)

        
        # Configure tree tags
        self.tree.tag_configure('group', background='#e6f3ff', font=('TkDefaultFont', 9, 'bold'))
        self.tree.tag_configure('file', background='#ffffff', font=('TkDefaultFont', 9))
        self.tree.tag_configure('selected', background='#ffe6e6', foreground='#cc0000', font=('TkDefaultFont', 9, 'bold'))
        
        # Scrollbars for treeview
        tree_scroll_y = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        tree_scroll_x = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=tree_scroll_y.set, xscrollcommand=tree_scroll_x.set)
        
        self.tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        tree_scroll_y.grid(row=0, column=1, sticky=(tk.N, tk.S))
        tree_scroll_x.grid(row=1, column=0, sticky=(tk.W, tk.E))
        
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)
        
        # Bind tree events
        self.tree.bind('<Double-Button-1>', self.toggle_selection)
        self.tree.bind('<<TreeviewSelect>>', self.on_tree_select)
        
        
        metadata_frame = ttk.Frame(right_frame)
        metadata_frame.pack(fill=tk.BOTH, expand=True, padx=(10, 0))
        
        self.metadata_text = tk.Text(metadata_frame, wrap=tk.WORD, font=('Consolas', 10),
                                     bg='#f8f8f8', relief='sunken', bd=1, padx=10, pady=5)
        metadata_scroll = ttk.Scrollbar(metadata_frame, orient=tk.VERTICAL, command=self.metadata_text.yview)
        self.metadata_text.configure(yscrollcommand=metadata_scroll.set)
        
        self.metadata_text.tag_configure('bold', font=('Consolas', 10, 'bold'))
        self.metadata_text.tag_configure('title_bold', font=('Consolas', 10, 'bold'))
        
        self.metadata_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        metadata_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Bottom frame - Action buttons
        action_frame = ttk.Frame(main_frame)
        action_frame.grid(row=3, column=0, columnspan=3, pady=(10, 0))
        
        ttk.Button(action_frame, text="Auto-Select (Keep Longest/Largest)", command=self.auto_select_longest).pack(side=tk.LEFT, padx=(0, 10))
        
        style.configure('Danger.TButton', foreground='red')
        ttk.Button(action_frame, text="Delete Selected Files (Del)", command=self.delete_selected,
                  style='Danger.TButton').pack(side=tk.RIGHT)
        
        # Status bar
        self.status_var = tk.StringVar(value=f"Ready - Default directory: {self.current_directory}")
        status_bar = ttk.Label(main_frame, textvariable=self.status_var, relief=tk.SUNKEN, padding=(5, 2))
        status_bar.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(10, 0))
    
    def browse_directory(self):
        """Open directory selection dialog"""
        directory = filedialog.askdirectory(title="Select Directory to Scan", initialdir=self.current_directory)
        if directory:
            if os.path.exists(directory) and os.access(directory, os.R_OK):
                self.current_directory = directory
                self.dir_var.set(directory)
                self.status_var.set(f"Directory selected: {directory}")
            else:
                messagebox.showerror("Error", "Selected directory is not accessible. Please check permissions.")
    
    def scan_duplicates(self):
        """Scan for duplicate files using multiprocessing and artist normalization"""
        self.current_directory = self.dir_var.get()
        
        if not self.current_directory or not os.path.exists(self.current_directory):
            messagebox.showwarning("Warning", "Please select a valid directory first.")
            return
        
        if not METADATA_AVAILABLE:
            messagebox.showerror("Error", "Metadata support not available. Please install tinytag: pip install tinytag")
            return
        
        # Clear previous results
        self.tree.delete(*self.tree.get_children())
        self.duplicate_groups.clear()
        self.selected_files.clear()
        self.item_data.clear()
        
        # Reset progress indicators
        self.progress['value'] = 0
        self.progress_label.config(text="Scanning...")
        self.status_var.set("Scanning for duplicates...")
        
        # Disable scan button during operation
        self.scan_button.config(text="Scanning...", state='disabled')
        
        # Start scanning in separate thread
        thread = threading.Thread(target=self._scan_worker)
        thread.daemon = True
        thread.start()
    
    def _scan_worker(self):
        """Worker thread for scanning duplicates with multiprocessing"""
        try:
            # Find audio files
            self.root.after(0, lambda: self.progress_label.config(text="Finding audio files..."))
            audio_files = self.file_ops.find_audio_files(self.current_directory)
            
            if not audio_files:
                self.root.after(0, lambda: self._scan_complete("No audio files found in the selected directory!"))
                return
            
            self.total_files = len(audio_files)
            
            # Process metadata using multiprocessing
            def progress_callback(completed: int, total: int):
                progress = (completed / total) * 90  # 90% for metadata processing
                self.root.after(0, lambda p=progress: self.progress.config(value=p))
                self.root.after(0, lambda c=completed, t=total: self.progress_label.config(
                    text=f"Processing metadata: {c}/{t} files"))
            
            print(f"{Fore.GREEN}Processing {self.total_files} files...{Style.RESET_ALL}")
            files_metadata = self.file_ops.process_files_parallel(audio_files, progress_callback)
            
            # Group duplicates by metadata
            self.root.after(0, lambda: self.progress_label.config(text="Grouping..."))
            duplicate_groups = self.duplicate_detector.group_by_metadata(files_metadata)

            # No conversion needed
            self.duplicate_groups = duplicate_groups
            
            # Update progress to complete
            self.root.after(0, lambda: self.progress.config(value=100))
            
            # Update UI on main thread
            self.root.after(0, lambda: self._populate_tree(duplicate_groups))
            
        except Exception as e:
            error_msg = f"Error during scan: {str(e)}"
            print(f"{Fore.RED}{error_msg}{Style.RESET_ALL}")
            self.root.after(0, lambda: self._scan_complete(error_msg))
    
    def _populate_tree(self, duplicates: Dict[str, List[str]]):
        """Populate treeview with duplicate groups and metadata"""
        self.progress.config(value=100)
        self.progress_label.config(text="scanning completed")
        self.scan_button.config(text="Scan for Duplicates", state='normal')
        
        if not duplicates:
            self.status_var.set("No duplicates found!")
            return
        
        for i, (group_name, files) in enumerate(duplicates.items(), 1):
            group_id = self.tree.insert('', 'end', text=f"{group_name}", # old text=f"Group {i}: {group_name}
                                       values=('', '', '', '', '', ''), tags=('group',))
            
            for file_path in files:
                metadata = MetadataHandler.extract_file_metadata(file_path)
                
                if not metadata.get('success', False):
                    continue
                
                filename = metadata['filename']
                title = metadata.get('title', '')
                # Display contributing artists in the UI
                contributing_artists = metadata.get('contributing_artists', '')
                size_mb = metadata['size_mb']
                duration = metadata['duration_formatted']
                quality = metadata['quality']
                
                file_id = self.tree.insert(group_id, 'end', text=filename,
                                          values=(title, contributing_artists, duration, size_mb, quality, '[ ]'), tags=('file',))
                
                self.item_data[file_id] = {
                    'file_path': file_path,
                    'group_files': files,
                    'metadata': metadata
                }
        
        # Expand all groups
        for item in self.tree.get_children():
            self.tree.item(item, open=True)
        
        total_groups = len(duplicates)
        total_files = sum(len(files) for files in duplicates.values())
        self.status_var.set(f"Found {total_groups} duplicate groups with {total_files} files total")
    
    def _scan_complete(self, message: str):
        """Complete scan with message and reset progress indicators"""
        self.progress.config(value=0)
        self.progress_label.config(text="")
        self.scan_button.config(text="Scan for Duplicates", state='normal')
        self.status_var.set(message)
    
    def toggle_selection(self, event):
        """Toggle file selection on double-click"""
        item = self.tree.selection()[0] if self.tree.selection() else None
        if not item or 'file' not in self.tree.item(item, 'tags'):
            return
        
        file_path = self.item_data.get(item, {}).get('file_path')
        if not file_path:
            return
        
        if file_path in self.selected_files:
            self.selected_files.remove(file_path)
            self.tree.set(item, 'select', '[ ]')
            self.tree.item(item, tags=('file',))
        else:
            self.selected_files.add(file_path)
            self.tree.set(item, 'select', '[X]')
            self.tree.item(item, tags=('file', 'selected'))
    
    def on_tree_select(self, event):
        """Handle tree selection to show metadata differences"""
        item = self.tree.selection()[0] if self.tree.selection() else None
        if not item or 'file' not in self.tree.item(item, 'tags'):
            self.metadata_text.delete(1.0, tk.END)
            return
        
        item_info = self.item_data.get(item, {})
        file_path = item_info.get('file_path')
        group_files = item_info.get('group_files', [])
        
        if not file_path:
            self.metadata_text.delete(1.0, tk.END)
            self.metadata_text.insert(1.0, "No file data available")
            return
        
        differences = self.duplicate_detector.get_metadata_differences(file_path, group_files)
        
        self.metadata_text.delete(1.0, tk.END)
        for text, tag in differences:
            if tag:
                self.metadata_text.insert(tk.END, text, tag)
            else:
                self.metadata_text.insert(tk.END, text)
    
    
    def duration_to_seconds(self, duration_str: str) -> int:
        """Convert duration string to seconds for sorting"""
        try:
            parts = duration_str.split(':')
            if len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            else:
                return 0
        except (ValueError, IndexError):
            return 0
    
    def auto_select_longest(self):
        """Auto-select files, keeping the longest duration first, then largest size"""
        self.selected_files.clear()
        
        for group_item in self.tree.get_children():
            files_in_group = []
            
            for file_item in self.tree.get_children(group_item):
                file_path = self.item_data.get(file_item, {}).get('file_path')
                if file_path:
                    duration_str = self.tree.set(file_item, 'length')
                    try:
                        size_mb = float(self.tree.set(file_item, 'size'))
                    except ValueError:
                        size_mb = 0
                    
                    duration_sec = self.duration_to_seconds(duration_str)
                    files_in_group.append((file_item, file_path, duration_sec, size_mb))
            
            if len(files_in_group) <= 1:
                continue
            
            files_in_group.sort(key=lambda x: (x[2], x[3]), reverse=True)
            
            for i, (file_item, file_path, duration_sec, size_mb) in enumerate(files_in_group):
                if i == 0:  # Keep the longest and largest
                    self.tree.set(file_item, 'select', '[ ]')
                    self.tree.item(file_item, tags=('file',))
                else:  # Select smaller ones for deletion
                    self.selected_files.add(file_path)
                    self.tree.set(file_item, 'select', '[X]')
                    self.tree.item(file_item, tags=('file', 'selected'))
        
        self.status_var.set(f"Auto-selected {len(self.selected_files)} shorter/smaller files for deletion")
    
    def delete_selected(self):
        """Delete selected files with backup"""
        if not self.selected_files:
            messagebox.showwarning("Warning", "No files selected for deletion.")
            return
        
        file_list = '\n'.join([Path(f).name for f in sorted(list(self.selected_files)[:10])])
        if len(self.selected_files) > 10:
            file_list += f'\n... and {len(self.selected_files) - 10} more files'
        
        confirm = messagebox.askyesno(
            "Confirm Deletion",
            f"Are you sure you want to delete {len(self.selected_files)} files?\n\n{file_list}\n\n"
            f"A backup list will be created before deletion.\n\n"
            f"This action cannot be undone!",
            icon='warning'
        )
        
        if not confirm:
            return
        
        # Create backup list
        backup_path = FileOperations.create_backup_list(self.selected_files, self.current_directory)
        
        # Delete files
        deleted_count, failed_deletions = FileOperations.delete_files(self.selected_files)
        
        # Show results
        result_msg = f"Successfully deleted {deleted_count} files."
        if backup_path:
            result_msg += f"\n\nBackup list created: {Path(backup_path).name}"
        
        if failed_deletions:
            error_msg = '\n'.join(failed_deletions[:5])
            if len(failed_deletions) > 5:
                error_msg += f'\n... and {len(failed_deletions) - 5} more errors'
            full_msg = result_msg + f"\n\nFailed to delete some files:\n{error_msg}"
            messagebox.showwarning("Deletion Results", full_msg)
        else:
            messagebox.showinfo("Success", result_msg)
        
        # Clear selection and refresh
        self.selected_files.clear()
        print(f"{Fore.GREEN}Deletion complete. Refreshing view...{Style.RESET_ALL}")
        self.scan_duplicates()


def main():
    """Main application entry point"""
    root = tk.Tk()
    app = AudioDuplicateDetectorUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
