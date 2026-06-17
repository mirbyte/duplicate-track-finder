import ctypes
import multiprocessing
import os
import platform
import re
import threading
import unicodedata
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# github/mirbyte

try:
    from colorama import Fore, Style, init
except ImportError:
    class _NoColor:
        """Fallback object used when colorama is not installed."""

        def __getattr__(self, _name: str) -> str:
            return ""

    Fore = Style = _NoColor()

    def init(*_args, **_kwargs) -> None:
        return None


# =============================================================================
# Application metadata and configuration
# =============================================================================

__version__ = "0.3"

APP_NAME = "Duplicate Track Finder"
APP_AUTHOR = "github/mirbyte"
APP_DESCRIPTION = "Find likely duplicate audio tracks by comparing normalized metadata."
APP_VERSION = __version__

DEBUG = os.getenv("DUPLICATE_TRACK_FINDER_DEBUG", "").lower() in {"1", "true", "yes", "on"}

SUPPORTED_AUDIO_EXTENSIONS = frozenset({
    ".flac", ".mp3", ".wav", ".m4a", ".ogg", ".aac", ".wma", ".opus", ".aiff", ".ape", ".alac",
})
LOSSLESS_AUDIO_EXTENSIONS = frozenset({".flac", ".wav", ".aiff", ".dsd", ".ape", ".alac"})

WINDOWS_MAX_PATH = 260
WINDOWS_LONG_PATH_PREFIX = "\\\\?\\"
DATETIME_DISPLAY_FORMAT = "%Y-%m-%d %H:%M:%S"
BACKUP_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"
BACKUP_FILENAME_TEMPLATE = "deleted_files_backup_{timestamp}.txt"
BACKUP_SEPARATOR_LENGTH = 60

DEFAULT_WINDOW_SIZE = "1400x900"
MIN_WINDOW_WIDTH = 1000
MIN_WINDOW_HEIGHT = 650
DEFAULT_TREE_ROW_HEIGHT = 25
METADATA_PROGRESS_PERCENT = 90
MAX_DELETE_PREVIEW_FILES = 10
DEFAULT_MAX_WORKERS = 4
DEFAULT_START_MAXIMIZED = True
BASE_DPI = 96
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
PROCESS_PER_MONITOR_DPI_AWARE = 2

CHECKED_MARKER = "[X]"
UNCHECKED_MARKER = "[ ]"

TREE_COLUMNS = ("title", "artist", "length", "size", "quality", "select")
TREE_COLUMN_HEADINGS = {
    "#0": "File Name",
    "title": "Title",
    "artist": "Contributing Artists",
    "length": "Length",
    "size": "Size (MB)",
    "quality": "Quality",
    "select": "Delete?",
}
TREE_COLUMN_WIDTHS = {
    "#0": (300, 200),
    "title": (200, 120),
    "artist": (300, 140),
    "length": (120, 40),
    "size": (120, 40),
    "quality": (150, 40),
    "select": (100, 40),
}

METADATA_COMPARE_FIELDS = (
    "title",
    "contributing_artists",
    "album_artist",
    "raw_artists",
    "normalized_artists_debug",
    "year",
    "quality",
    "modified_date",
    "created_date",
)

METADATA_FIELD_LABELS = {
    "title": "Title",
    "contributing_artists": "Contributing Artists",
    "album_artist": "Album Artist",
    "raw_artists": "Raw Artists (Before Normalization)",
    "normalized_artists_debug": "Normalized Artists (After Processing)",
    "album": "Album",
    "year": "Year",
    "genre": "Genre",
    "duration_formatted": "Duration",
    "bitrate": "Bitrate",
    "samplerate": "Sample Rate",
    "channels": "Channels",
    "size_mb": "Size (MB)",
    "quality": "Quality",
    "modified_date": "Modified Date",
    "created_date": "Created Date",
}


# =============================================================================
# Logging helpers
# =============================================================================

def log_message(message: str, color: str = "", *, debug_only: bool = False) -> None:
    """Print a console message, optionally hidden unless DEBUG is enabled."""
    if debug_only and not DEBUG:
        return

    if color:
        print(f"{color}{message}{Style.RESET_ALL}")
    else:
        print(message)


def log_debug(message: str, color: str = Fore.CYAN) -> None:
    """Print a debug message only when DEBUG is enabled."""
    log_message(message, color, debug_only=True)


def log_info(message: str, color: str = Fore.GREEN) -> None:
    """Print an informational message."""
    log_message(message, color)


def log_warning(message: str) -> None:
    """Print a warning message."""
    log_message(message, Fore.YELLOW)


def log_error(message: str) -> None:
    """Print an error message."""
    log_message(message, Fore.RED)


# Initialize colorama for Windows compatibility.
init()


# =============================================================================
# High-DPI support
# =============================================================================

def enable_windows_dpi_awareness() -> None:
    """Opt into sharp high-DPI rendering on Windows before creating Tk windows."""
    if platform.system() != "Windows":
        return

    try:
        user32 = ctypes.windll.user32
        try:
            user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            user32.SetProcessDpiAwarenessContext.restype = ctypes.c_bool
            if user32.SetProcessDpiAwarenessContext(
                ctypes.c_void_p(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
            ):
                return
        except (AttributeError, OSError, ValueError):
            pass

        try:
            shcore = ctypes.windll.shcore
            shcore.SetProcessDpiAwareness.argtypes = [ctypes.c_int]
            shcore.SetProcessDpiAwareness.restype = ctypes.HRESULT
            if shcore.SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE) == 0:
                return
        except (AttributeError, OSError, ValueError):
            pass

        try:
            user32.SetProcessDPIAware()
        except (AttributeError, OSError, ValueError):
            pass
    except Exception as error:
        log_debug(f"Could not enable Windows DPI awareness: {error}", Fore.YELLOW)


def configure_tk_scaling(root: tk.Tk) -> float:
    """Set Tk's point scaling and return the current monitor scale factor."""
    try:
        dpi = float(root.winfo_fpixels("1i"))
        root.tk.call("tk", "scaling", dpi / 72.0)
        return max(1.0, dpi / BASE_DPI)
    except tk.TclError as error:
        log_debug(f"Could not configure Tk scaling: {error}", Fore.YELLOW)
        return 1.0


def scale_pixels(value: int, scale: float) -> int:
    """Scale pixel values while keeping a minimum of 1 pixel for positive values."""
    if value <= 0:
        return value
    return max(1, round(value * scale))


def scale_geometry(geometry: str, scale: float) -> str:
    """Scale a Tk geometry string like '1400x900'."""
    match = re.fullmatch(r"(\d+)x(\d+)([+-]\d+[+-]\d+)?", geometry)
    if not match:
        return geometry

    width, height, position = match.groups()
    scaled = f"{scale_pixels(int(width), scale)}x{scale_pixels(int(height), scale)}"
    return scaled + (position or "")


def maximize_window(root: tk.Tk) -> None:
    """Open the app maximized by default, with cross-platform fallbacks."""
    if not DEFAULT_START_MAXIMIZED:
        return

    try:
        root.update_idletasks()
    except tk.TclError:
        pass

    # Windows: maximized, not borderless fullscreen. Keeps taskbar/titlebar behavior.
    try:
        root.state("zoomed")
        return
    except tk.TclError:
        pass

    # Some Unix/X11 window managers support this Tk attribute.
    try:
        root.attributes("-zoomed", True)
        return
    except tk.TclError:
        pass

    # Last-resort fallback: size the window to the screen.
    try:
        width = root.winfo_screenwidth()
        height = root.winfo_screenheight()
        root.geometry(f"{width}x{height}+0+0")
    except tk.TclError as error:
        log_debug(f"Could not maximize window: {error}", Fore.YELLOW)


# =============================================================================
# Optional dependency checks
# =============================================================================

try:
    from tinytag import TinyTag
    METADATA_AVAILABLE = True
except ImportError:
    METADATA_AVAILABLE = False
    log_warning("Warning: tinytag not installed. Install with 'pip install tinytag' for metadata support.")


# =============================================================================
# Metadata handling
# =============================================================================

class MetadataHandler:
    """Extracts file metadata and normalizes text for duplicate comparison."""

    @staticmethod
    def safe_path(path_str: str) -> Path:
        """Return a Path, adding the Windows long-path prefix when needed."""
        try:
            path = Path(path_str)
            if platform.system() == "Windows":
                abs_path_str = str(path.resolve())
                if (
                    len(abs_path_str) >= WINDOWS_MAX_PATH
                    and not abs_path_str.startswith(WINDOWS_LONG_PATH_PREFIX)
                ):
                    abs_path_str = WINDOWS_LONG_PATH_PREFIX + abs_path_str
                return Path(abs_path_str)
            return path
        except (OSError, ValueError) as error:
            log_warning(f"Warning: Path conversion failed for {path_str}: {error}")
            return Path(path_str)

    @staticmethod
    def _ascii_normalize(text: str) -> str:
        """Normalize Unicode text and strip accents where possible."""
        normalized = unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", text.strip()))
        try:
            return normalized.encode("ascii", "ignore").decode("ascii")
        except Exception:
            return normalized

    @staticmethod
    def get_audio_quality_indicator(file_path: Path) -> str:
        """Classify an audio file as lossless or lossy from its extension."""
        return "Lossless" if file_path.suffix.lower() in LOSSLESS_AUDIO_EXTENSIONS else "Lossy"

    @staticmethod
    def format_timestamp(timestamp: float) -> str:
        """Format a filesystem timestamp for display."""
        try:
            return datetime.fromtimestamp(timestamp).strftime(DATETIME_DISPLAY_FORMAT)
        except (OSError, ValueError, OverflowError):
            return "Unknown"

    @staticmethod
    def normalize_single_artist_name(name: str) -> str:
        """Normalize one artist name for stable duplicate comparisons."""
        if not name:
            return ""

        name = MetadataHandler._ascii_normalize(name).lower()
        name = re.sub(r"^(feat\.?|ft\.?|featuring)\s+", "", name, flags=re.IGNORECASE)
        name = re.sub(r"\s+(feat\.?|ft\.?|featuring).*$", "", name, flags=re.IGNORECASE)
        name = re.sub(r"\s*\([^)]*\)", "", name)
        name = re.sub(r"[\"“”'‘’`]", "", name)
        name = name.replace(".", "").replace("-", " ")
        name = re.sub(r"\s+", " ", name).strip()
        return name

    @staticmethod
    def normalize_artists(artist_text: str) -> Set[str]:
        """Normalize an artist/contributor string into comparable artist names."""
        if not artist_text:
            return set()

        log_debug(f"Normalizing artists: '{artist_text}'")
        cleaned = MetadataHandler._ascii_normalize(artist_text).lower()
        cleaned = re.sub(r"[;,\s]+$", "", cleaned)
        cleaned = cleaned.replace(";", ",")
        cleaned = re.sub(r"\s*[&+/\\|]\s*", ",", cleaned)
        # Do not split on a standalone "x" here: it can be a collaboration marker,
        # but it can also be part of real names such as "Malcolm X".
        cleaned = re.sub(
            r"\s+(and|feat\.?|ft\.?|vs\.?|versus|with)\s+",
            ",",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r",+", ",", cleaned)
        cleaned = re.sub(r"\s*,\s*", ",", cleaned).strip(", ")

        artists = {
            normalized
            for artist in cleaned.split(",")
            if (normalized := MetadataHandler.normalize_single_artist_name(artist))
        }

        log_debug(f"Normalized artists: {sorted(artists)}", Fore.GREEN)
        return artists

    @staticmethod
    def get_title_first_word(title: str) -> str:
        """Return the first meaningful word in a title, ignoring basic articles."""
        if not title:
            return ""

        title = unicodedata.normalize("NFKD", title).strip()
        title = re.sub(r"^(the|a|an)\s+", "", title, flags=re.IGNORECASE)
        words = title.split()
        if not words:
            return ""

        return re.sub(r"[^\w\s]", "", words[0].lower())

    @staticmethod
    def extract_preferred_artist_data(tag) -> Tuple[str, str, str, Set[str]]:
        """Return normalized artist text, raw artist text, source field, and artist set."""
        artist_fields = (
            ("artist", "artist"),
            ("albumartist", "album artist"),
            ("composer", "composer"),
        )

        for field_name, display_name in artist_fields:
            raw_value = getattr(tag, field_name, None)
            if not raw_value:
                continue

            raw_artist_text = str(raw_value).strip()
            if not raw_artist_text:
                continue

            normalized_artists = MetadataHandler.normalize_artists(raw_artist_text)
            if normalized_artists:
                normalized_artist_text = ", ".join(sorted(normalized_artists))
                log_debug(
                    f"Using {display_name} field: '{normalized_artist_text}'",
                    Fore.GREEN,
                )
                return normalized_artist_text, raw_artist_text, display_name, normalized_artists

        log_debug("No artist information found in artist, album artist, or composer fields", Fore.RED)
        return "", "", "", set()

    @staticmethod
    def extract_file_metadata(file_path_str: str) -> Dict:
        """Extract file stats and audio metadata for one audio file."""
        file_path = MetadataHandler.safe_path(file_path_str)
        metadata = {
            "file_path": file_path_str,
            "filename": Path(file_path_str).name,
            "size_mb": 0,
            "size_bytes": 0,
            "duration_formatted": "",
            "quality": MetadataHandler.get_audio_quality_indicator(file_path),
            "modified_date": "Unknown",
            "created_date": "Unknown",
            "title": "",
            "contributing_artists": "",
            "album_artist": "",
            "artist_source": "",
            "raw_artists": "",
            "normalized_artists": [],
            "normalized_artists_debug": "",
            "success": True,
        }

        try:
            stat = os.stat(file_path)
        except (PermissionError, OSError) as error:
            metadata["file_error"] = str(error)
            metadata["success"] = False
            return metadata

        metadata["size_bytes"] = stat.st_size
        metadata["size_mb"] = round(stat.st_size / (1024 * 1024))
        metadata["modified"] = stat.st_mtime
        metadata["modified_date"] = MetadataHandler.format_timestamp(stat.st_mtime)

        if platform.system() == "Windows":
            metadata["created"] = stat.st_ctime
            metadata["created_date"] = MetadataHandler.format_timestamp(stat.st_ctime)
        elif hasattr(stat, "st_birthtime"):
            metadata["created"] = stat.st_birthtime
            metadata["created_date"] = MetadataHandler.format_timestamp(stat.st_birthtime)
        else:
            metadata["created"] = stat.st_mtime
            metadata["created_date"] = metadata["modified_date"]

        if not METADATA_AVAILABLE:
            return metadata

        try:
            tag = TinyTag.get(str(file_path))
            (
                normalized_artist_text,
                raw_artist_text,
                artist_source,
                normalized_artist_set,
            ) = MetadataHandler.extract_preferred_artist_data(tag)
            normalized_artist_list = sorted(normalized_artist_set)

            metadata.update({
                "title": tag.title or "",
                "contributing_artists": normalized_artist_text,
                "album_artist": tag.albumartist or "",
                "album": tag.album or "",
                "year": tag.year or "",
                "genre": tag.genre or "",
                "duration": tag.duration or 0,
                "bitrate": round(tag.bitrate) if tag.bitrate else 0,
                "samplerate": tag.samplerate or 0,
                "channels": tag.channels or 0,
                "artist": normalized_artist_text,
                "artist_source": artist_source,
                "raw_artists": raw_artist_text,
                "normalized_artists": normalized_artist_list,
                "normalized_artists_debug": ", ".join(normalized_artist_list),
            })

            if metadata["duration"]:
                minutes = int(metadata["duration"] // 60)
                seconds = int(metadata["duration"] % 60)
                metadata["duration_formatted"] = f"{minutes}:{seconds:02d}"
        except Exception as error:
            metadata["metadata_error"] = str(error)
            log_debug(f"Metadata read failed for {file_path}: {error}", Fore.YELLOW)

        return metadata

# =============================================================================
# File system operations
# =============================================================================

class FileOperations:
    """Find audio files, extract metadata, and perform guarded file deletion."""

    def __init__(self, extensions: Set[str] = SUPPORTED_AUDIO_EXTENSIONS):
        self.extensions = frozenset(extension.lower() for extension in extensions)

    def find_audio_files(self, directory: str) -> List[str]:
        """Find supported audio files under a directory."""
        base_path = Path(directory)
        if not base_path.exists() or not base_path.is_dir():
            log_error(f"Directory does not exist or is not a folder: {directory}")
            return []

        audio_files = []
        try:
            for file_path in base_path.rglob("*"):
                if file_path.is_file() and file_path.suffix.lower() in self.extensions:
                    audio_files.append(str(file_path))
        except OSError as error:
            log_error(f"Could not scan directory {directory}: {error}")

        return audio_files

    def process_files_parallel(self, file_paths: List[str], progress_callback=None, max_workers=None, should_cancel=None) -> List[Dict]:
        """Extract metadata in parallel, falling back to sequential processing if needed."""
        if not file_paths:
            return []

        if should_cancel and should_cancel():
            return []

        if max_workers is None:
            try:
                max_workers = multiprocessing.cpu_count() or DEFAULT_MAX_WORKERS
            except NotImplementedError:
                max_workers = DEFAULT_MAX_WORKERS

        worker_count = max(1, min(max_workers, len(file_paths)))
        metadata_list = []
        completed = 0

        try:
            with ProcessPoolExecutor(max_workers=worker_count) as executor:
                future_to_path = {
                    executor.submit(MetadataHandler.extract_file_metadata, path): path
                    for path in file_paths
                }

                for future in as_completed(future_to_path):
                    if should_cancel and should_cancel():
                        for pending_future in future_to_path:
                            pending_future.cancel()
                        log_info("Metadata processing cancelled.")
                        break

                    path = future_to_path[future]
                    try:
                        metadata_list.append(future.result())
                    except Exception as error:
                        log_error(f"Error processing {Path(path).name}: {error}")
                        metadata_list.append({
                            "file_path": path,
                            "filename": Path(path).name,
                            "error": str(error),
                            "success": False,
                        })

                    completed += 1
                    if progress_callback:
                        progress_callback(completed, len(file_paths))
        except Exception as error:
            log_error(f"Multiprocessing error: {error}")
            return self._process_files_sequential(file_paths, progress_callback, should_cancel)

        return metadata_list

    def _process_files_sequential(self, file_paths: List[str], progress_callback=None, should_cancel=None) -> List[Dict]:
        """Extract metadata without multiprocessing."""
        metadata_list = []
        for index, path in enumerate(file_paths, start=1):
            if should_cancel and should_cancel():
                log_info("Metadata processing cancelled.")
                break

            metadata_list.append(MetadataHandler.extract_file_metadata(path))
            if progress_callback:
                progress_callback(index, len(file_paths))
        return metadata_list

    @staticmethod
    def create_backup_list(files_to_delete: Set[str], directory: str) -> Optional[str]:
        """Write a timestamped list of files selected for deletion."""
        if not files_to_delete:
            return None

        try:
            timestamp = datetime.now().strftime(BACKUP_TIMESTAMP_FORMAT)
            backup_filename = BACKUP_FILENAME_TEMPLATE.format(timestamp=timestamp)
            backup_directory = MetadataHandler.safe_path(directory)
            backup_path = backup_directory / backup_filename

            with open(backup_path, "w", encoding="utf-8") as backup_file:
                backup_file.write(f"{APP_NAME} - Deleted Files Backup\n")
                backup_file.write(f"Date: {datetime.now().strftime(DATETIME_DISPLAY_FORMAT)}\n")
                backup_file.write(f"Directory: {directory}\n")
                backup_file.write("=" * BACKUP_SEPARATOR_LENGTH + "\n\n")

                for file_path in sorted(files_to_delete):
                    backup_file.write(f"{file_path}\n")

            return str(backup_path)
        except OSError as error:
            log_warning(f"Could not create backup list: {error}")
            return None

    @staticmethod
    def delete_files(files_to_delete: Set[str]) -> Tuple[int, List[str]]:
        """Delete selected files and report any failures."""
        deleted_count = 0
        failed_deletions = []

        for file_path in files_to_delete:
            try:
                safe_file_path = MetadataHandler.safe_path(file_path)
                if not safe_file_path.is_file():
                    failed_deletions.append(f"{Path(file_path).name}: Not a file")
                    continue

                os.remove(safe_file_path)
                deleted_count += 1
            except PermissionError:
                failed_deletions.append(f"{Path(file_path).name}: Permission denied")
            except FileNotFoundError:
                failed_deletions.append(f"{Path(file_path).name}: File not found")
            except OSError as error:
                failed_deletions.append(f"{Path(file_path).name}: {error}")

        return deleted_count, failed_deletions

# =============================================================================
# Duplicate detection
# =============================================================================

class DuplicateDetector:
    """Groups likely duplicate tracks by normalized title and artist metadata."""

    @staticmethod
    def extract_base_title(title: str) -> str:
        """Remove common version/feature text from a title before comparison."""
        if not title:
            return ""

        base_title = title.lower().strip()
        base_title = re.sub(r"\s*[\(\[].*?[\)\]]", "", base_title)
        base_title = re.sub(
            r"\s+(feat\.?|ft\.?|featuring)\s+[^-]*$",
            "",
            base_title,
            flags=re.IGNORECASE,
        )
        base_title = re.sub(
            r"\s*[-–—]\s*(extended|radio|club|original|vocal|instrumental|acoustic|remix|mix|edit|version|dub).*$",
            "",
            base_title,
            flags=re.IGNORECASE,
        )
        return re.sub(r"\s+", " ", base_title).strip()

    def group_by_metadata(self, files_metadata: List[Dict]) -> Dict[str, List[str]]:
        """Group files whose base titles match and whose artists overlap."""
        candidate_files = []

        for metadata in files_metadata:
            if not metadata.get("success", False):
                continue

            title = metadata.get("title", "")
            artist_text = metadata.get("contributing_artists", "")
            file_path = metadata.get("file_path", "")
            if not title or not artist_text or not file_path:
                continue

            base_title = self.extract_base_title(title)
            normalized_artists = metadata.get("normalized_artists") or []
            artists = set(normalized_artists)
            if not artists:
                artists = MetadataHandler.normalize_artists(artist_text)
            if not base_title or not artists:
                continue

            candidate_files.append({
                "file_path": file_path,
                "base_title": base_title,
                "artists": artists,
                "grouped": False,
            })

            log_debug(f"File: {Path(file_path).name}", Fore.MAGENTA)
            log_debug(f"  Base title: '{base_title}'")
            log_debug(f"  Artists: {sorted(artists)}\n")

        title_buckets: Dict[str, List[Dict]] = defaultdict(list)
        for file_info in candidate_files:
            title_buckets[file_info["base_title"]].append(file_info)

        groups = []
        for bucket_files in title_buckets.values():
            if len(bucket_files) < 2:
                continue

            for index, first_file in enumerate(bucket_files):
                if first_file["grouped"]:
                    continue

                current_group = [first_file]
                first_file["grouped"] = True

                for second_file in bucket_files[index + 1:]:
                    if second_file["grouped"]:
                        continue

                    shared_artists = first_file["artists"] & second_file["artists"]
                    if shared_artists:
                        current_group.append(second_file)
                        second_file["grouped"] = True

                        log_debug("✓ MATCH FOUND!", Fore.GREEN)
                        log_debug(f"  '{first_file['base_title']}' == '{second_file['base_title']}'")
                        log_debug(f"  Common artists: {sorted(shared_artists)}")
                        log_debug(f"  File1 artists: {sorted(first_file['artists'])}")
                        log_debug(f"  File2 artists: {sorted(second_file['artists'])}\n")

                if len(current_group) >= 2:
                    groups.append(current_group)

        duplicate_groups = {}
        for group in groups:
            first_file = group[0]
            artists_text = ", ".join(sorted(first_file["artists"]))
            group_name = f"{first_file['base_title'].title()} - {artists_text}"
            duplicate_groups[group_name] = [file_info["file_path"] for file_info in group]

        return duplicate_groups

    def get_metadata_differences(self, selected_file_path: str, group_metadata: List[Dict]) -> List[Tuple[str, Optional[str]]]:
        """Return formatted cached metadata differences for display in the side panel."""
        if not METADATA_AVAILABLE:
            return [("Audio metadata not available (Install tinytag: pip install tinytag)", None)]

        all_metadata = [metadata for metadata in group_metadata if metadata.get("file_path")]
        selected_index = next(
            (index for index, metadata in enumerate(all_metadata) if metadata.get("file_path") == selected_file_path),
            -1,
        )

        if selected_index == -1:
            return [("Could not find metadata for selected file", None)]

        differing_fields = {}
        for field in METADATA_COMPARE_FIELDS:
            values = {
                str(value) if (value := metadata.get(field, "")) not in [None, "", 0, "Unknown"] else ""
                for metadata in all_metadata
            }
            if len(values) > 1:
                differing_fields[field] = True

        if not differing_fields:
            return [
                (f"Selected: {Path(selected_file_path).name}\n\n", None),
                ("✓ No metadata differences found\n", None),
                ("All files in this group have identical metadata.", None),
            ]

        result = [
            (f"Selected: {Path(selected_file_path).name}\n", None),
            ("=" * 70 + "\n\n", None),
        ]

        for field in differing_fields:
            label = METADATA_FIELD_LABELS.get(field)
            if not label:
                continue

            result.append((f"{label}:\n", None))
            for index, metadata in enumerate(all_metadata):
                filename = Path(metadata["file_path"]).name
                value = metadata.get(field, "")
                display_value = str(value) if value not in [None, "", 0, "Unknown"] else "Unknown"
                prefix = "► " if index == selected_index else "  "
                tag = "title_bold" if field == "title" else None
                result.append((f"{prefix}{filename} = {display_value}\n", tag))

            result.append(("\n", None))

        return result

# =============================================================================
# User interface
# =============================================================================

class AudioDuplicateDetectorUI:
    """Main UI class handling all interface operations"""
    
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_NAME} v{APP_VERSION} - {APP_AUTHOR}")
        self.ui_scale = configure_tk_scaling(self.root)
        self.root.geometry(scale_geometry(DEFAULT_WINDOW_SIZE, self.ui_scale))
        self.root.minsize(
            scale_pixels(MIN_WINDOW_WIDTH, self.ui_scale),
            scale_pixels(MIN_WINDOW_HEIGHT, self.ui_scale),
        )
        
        # Initialize core components
        self.file_ops = FileOperations()
        self.duplicate_detector = DuplicateDetector()
        
        # Set current directory as default
        self.current_directory = os.getcwd()
        self.duplicate_groups: Dict[str, List[str]] = {}
        self.selected_files: Set[str] = set()
        self.item_data: Dict[str, Dict] = {}
        self.file_metadata_by_path: Dict[str, Dict] = {}
        self.cancel_event = threading.Event()
        
        self.total_files = 0

        self.setup_ui()
        self.setup_keyboard_shortcuts()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
    
    def on_close(self):
        """Cancel any active scan before closing the window."""
        self.cancel_event.set()
        self.root.destroy()

    def setup_keyboard_shortcuts(self):
        """Register keyboard shortcuts for common actions."""
        self.root.bind('<Control-a>', lambda _event: self.select_all())
        self.root.bind('<Control-A>', lambda _event: self.select_all())
        self.root.bind('<Delete>', lambda _event: self.delete_selected())
        self.root.focus_set()

    def px(self, value: int) -> int:
        """Return a DPI-scaled pixel value for layout dimensions."""
        return scale_pixels(value, self.ui_scale)
    
    def setup_ui(self):
        """Setup the main user interface with improved styling"""
        style = ttk.Style()
        style.configure("Treeview", rowheight=self.px(DEFAULT_TREE_ROW_HEIGHT))
        style.configure("Treeview.Heading", font=('TkDefaultFont', 9, 'bold'))
        
        main_frame = ttk.Frame(self.root, padding=self.px(10))
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(2, weight=1)
        
        # Directory selection frame
        dir_frame = ttk.Frame(main_frame)
        dir_frame.grid(row=0, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, self.px(10)))
        dir_frame.columnconfigure(1, weight=1)
        
        ttk.Label(dir_frame, text="Directory:").grid(row=0, column=0, padx=(0, self.px(10)))
        self.dir_var = tk.StringVar(value=self.current_directory)
        ttk.Entry(dir_frame, textvariable=self.dir_var, state="readonly").grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, self.px(10)))
        ttk.Button(dir_frame, text="Browse", command=self.browse_directory).grid(row=0, column=2, padx=(0, self.px(10)))
        self.scan_button = ttk.Button(dir_frame, text="Scan for Duplicates", command=self.scan_duplicates)
        self.scan_button.grid(row=0, column=3, padx=(0, self.px(10)))
        self.cancel_button = ttk.Button(dir_frame, text="Cancel", command=self.cancel_scan, state='disabled')
        self.cancel_button.grid(row=0, column=4)
        
        # Progress bar and label
        progress_frame = ttk.Frame(main_frame)
        progress_frame.grid(row=1, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, self.px(10)))
        progress_frame.columnconfigure(0, weight=1)
        
        self.progress = ttk.Progressbar(progress_frame, mode='determinate')
        self.progress.grid(row=0, column=0, sticky=(tk.W, tk.E))
        self.progress_label = ttk.Label(progress_frame, text="")
        self.progress_label.grid(row=1, column=0, pady=(self.px(2), 0))
        
        # Paned window for split view
        paned = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        paned.grid(row=2, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Left panel - Duplicate groups
        left_frame = ttk.Frame(paned)
        paned.add(left_frame, weight=4)
        
        ttk.Label(left_frame, text="Duplicate Groups", font=('TkDefaultFont', 11, 'bold')).pack(pady=(0, self.px(5)))
        
        # Right panel - Metadata differences
        right_frame = ttk.Frame(paned)
        paned.add(right_frame, weight=1)
        
        ttk.Label(right_frame, text="Metadata Differences", font=('TkDefaultFont', 11, 'bold')).pack(pady=(0, self.px(5)))
        
        # Treeview for duplicates
        tree_frame = ttk.Frame(left_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        
        self.tree = ttk.Treeview(tree_frame, columns=TREE_COLUMNS,
                                show='tree headings', selectmode='extended')
        
        for column_id, heading in TREE_COLUMN_HEADINGS.items():
            self.tree.heading(column_id, text=heading)

        for column_id, (width, minwidth) in TREE_COLUMN_WIDTHS.items():
            anchor = 'center' if column_id != '#0' else tk.W
            stretch = column_id not in {'length', 'size', 'quality', 'select'}
            self.tree.column(column_id, width=self.px(width), minwidth=self.px(minwidth), anchor=anchor, stretch=stretch)

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
        metadata_frame.pack(fill=tk.BOTH, expand=True, padx=(self.px(10), 0))
        
        self.metadata_text = tk.Text(metadata_frame, wrap=tk.WORD, font=('Consolas', 10),
                                     bg='#f8f8f8', relief='sunken', bd=1, padx=self.px(10), pady=self.px(5))
        metadata_scroll = ttk.Scrollbar(metadata_frame, orient=tk.VERTICAL, command=self.metadata_text.yview)
        self.metadata_text.configure(yscrollcommand=metadata_scroll.set)
        
        self.metadata_text.tag_configure('bold', font=('Consolas', 10, 'bold'))
        self.metadata_text.tag_configure('title_bold', font=('Consolas', 10, 'bold'))
        
        self.metadata_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        metadata_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Bottom frame - Action buttons
        action_frame = ttk.Frame(main_frame)
        action_frame.grid(row=3, column=0, columnspan=3, pady=(self.px(10), 0))
        
        ttk.Button(action_frame, text="Auto-Select (Keep Longest/Largest)", command=self.auto_select_longest).pack(side=tk.LEFT, padx=(0, self.px(10)))
        
        style.configure('Danger.TButton', foreground='red')
        ttk.Button(action_frame, text="Delete Selected Files (Del)", command=self.delete_selected,
                  style='Danger.TButton').pack(side=tk.RIGHT)
        
        # Status bar
        self.status_var = tk.StringVar(value=f"Ready - Default directory: {self.current_directory}")
        status_bar = ttk.Label(main_frame, textvariable=self.status_var, relief=tk.SUNKEN, padding=(self.px(5), self.px(2)))
        status_bar.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(self.px(10), 0))
    
    def browse_directory(self):
        """Open the directory picker and store an accessible folder."""
        directory = filedialog.askdirectory(title="Select Directory to Scan", initialdir=self.current_directory)
        if not directory:
            return

        selected_path = Path(directory)
        if selected_path.exists() and selected_path.is_dir() and os.access(selected_path, os.R_OK):
            self.current_directory = directory
            self.dir_var.set(directory)
            self.status_var.set(f"Directory selected: {directory}")
        else:
            messagebox.showerror("Error", "Selected directory is not accessible. Please check permissions.")
    
    def cancel_scan(self):
        """Request cancellation for the current scan."""
        self.cancel_event.set()
        self.status_var.set("Cancelling scan...")
        self.cancel_button.config(state='disabled')

    def scan_duplicates(self):
        """Scan the selected directory for likely duplicate audio files."""
        self.current_directory = self.dir_var.get()
        selected_path = Path(self.current_directory)

        if not self.current_directory or not selected_path.exists() or not selected_path.is_dir():
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
        self.file_metadata_by_path.clear()
        
        # Reset progress indicators
        self.progress['value'] = 0
        self.progress_label.config(text="Scanning...")
        self.status_var.set("Scanning for duplicates...")
        self.cancel_event.clear()
        
        # Disable scan button during operation
        self.scan_button.config(text="Scanning...", state='disabled')
        self.cancel_button.config(state='normal')
        
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

            if self.cancel_event.is_set():
                self.root.after(0, lambda: self._scan_complete("Scan cancelled."))
                return
            
            if not audio_files:
                self.root.after(0, lambda: self._scan_complete("No audio files found in the selected directory!"))
                return
            
            self.total_files = len(audio_files)
            
            def progress_callback(completed: int, total: int):
                if total <= 0 or self.cancel_event.is_set():
                    return

                progress = (completed / total) * METADATA_PROGRESS_PERCENT
                self.root.after(0, lambda p=progress: self.progress.config(value=p))
                self.root.after(0, lambda c=completed, t=total: self.progress_label.config(
                    text=f"Processing metadata: {c}/{t} files"))
            
            log_info(f"Processing {self.total_files} files...")
            files_metadata = self.file_ops.process_files_parallel(
                audio_files,
                progress_callback,
                should_cancel=self.cancel_event.is_set,
            )

            if self.cancel_event.is_set():
                self.root.after(0, lambda: self._scan_complete("Scan cancelled."))
                return

            self.file_metadata_by_path = {
                metadata["file_path"]: metadata
                for metadata in files_metadata
                if metadata.get("file_path")
            }
            
            # Group duplicates by metadata
            self.root.after(0, lambda: self.progress_label.config(text="Grouping..."))
            duplicate_groups = self.duplicate_detector.group_by_metadata(files_metadata)

            if self.cancel_event.is_set():
                self.root.after(0, lambda: self._scan_complete("Scan cancelled."))
                return

            self.duplicate_groups = duplicate_groups

            self.root.after(0, lambda: self.progress.config(value=100))
            self.root.after(0, lambda: self._populate_tree(duplicate_groups))

        except Exception as error:
            error_msg = f"Error during scan: {error}"
            log_error(error_msg)
            self.root.after(0, lambda: self._scan_complete(error_msg))
    
    def _populate_tree(self, duplicates: Dict[str, List[str]]):
        """Populate treeview with duplicate groups and metadata"""
        self.progress.config(value=100)
        self.progress_label.config(text="Scan complete")
        self.scan_button.config(text="Scan for Duplicates", state='normal')
        self.cancel_button.config(state='disabled')
        
        if not duplicates:
            self.status_var.set("No duplicates found!")
            return
        
        for group_name, files in duplicates.items():
            group_id = self.tree.insert('', 'end', text=group_name,
                                       values=('', '', '', '', '', ''), tags=('group',))

            group_metadata = []
            for file_path in files:
                metadata = self.file_metadata_by_path.get(file_path)
                if metadata is None:
                    metadata = {
                        "file_path": file_path,
                        "filename": Path(file_path).name,
                        "error": "Metadata was not found in the scan cache",
                        "success": False,
                    }
                    log_warning(f"Missing cached metadata for {Path(file_path).name}")
                group_metadata.append(metadata)

            for metadata in group_metadata:
                file_path = metadata.get("file_path", "")
                filename = metadata.get("filename") or Path(file_path).name

                if not metadata.get('success', False):
                    error_message = (
                        metadata.get("metadata_error")
                        or metadata.get("file_error")
                        or metadata.get("error")
                        or "Metadata unavailable"
                    )
                    file_id = self.tree.insert(
                        group_id,
                        'end',
                        text=filename,
                        values=("Metadata unavailable", error_message, "", "", "", UNCHECKED_MARKER),
                        tags=('file',),
                    )
                else:
                    title = metadata.get('title', '')
                    contributing_artists = metadata.get('contributing_artists', '')
                    size_mb = metadata.get('size_mb', 0)
                    duration = metadata.get('duration_formatted', '')
                    quality = metadata.get('quality', '')

                    file_id = self.tree.insert(
                        group_id,
                        'end',
                        text=filename,
                        values=(title, contributing_artists, duration, size_mb, quality, UNCHECKED_MARKER),
                        tags=('file',),
                    )

                self.item_data[file_id] = {
                    'file_path': file_path,
                    'group_files': files,
                    'group_metadata': group_metadata,
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
        self.cancel_button.config(state='disabled')
        self.status_var.set(message)
    
    def toggle_selection(self, _event):
        """Toggle file selection on double-click"""
        item = self.tree.selection()[0] if self.tree.selection() else None
        if not item or 'file' not in self.tree.item(item, 'tags'):
            return
        
        file_path = self.item_data.get(item, {}).get('file_path')
        if not file_path:
            return
        
        if file_path in self.selected_files:
            self.selected_files.remove(file_path)
            self.tree.set(item, 'select', UNCHECKED_MARKER)
            self.tree.item(item, tags=('file',))
        else:
            self.selected_files.add(file_path)
            self.tree.set(item, 'select', CHECKED_MARKER)
            self.tree.item(item, tags=('file', 'selected'))
    
    def on_tree_select(self, _event):
        """Handle tree selection to show metadata differences"""
        item = self.tree.selection()[0] if self.tree.selection() else None
        if not item or 'file' not in self.tree.item(item, 'tags'):
            self.metadata_text.delete(1.0, tk.END)
            return
        
        item_info = self.item_data.get(item, {})
        file_path = item_info.get('file_path')
        group_metadata = item_info.get('group_metadata', [])
        
        if not file_path:
            self.metadata_text.delete(1.0, tk.END)
            self.metadata_text.insert(1.0, "No file data available")
            return
        
        differences = self.duplicate_detector.get_metadata_differences(file_path, group_metadata)
        
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
                    self.tree.set(file_item, 'select', UNCHECKED_MARKER)
                    self.tree.item(file_item, tags=('file',))
                else:  # Select smaller ones for deletion
                    self.selected_files.add(file_path)
                    self.tree.set(file_item, 'select', CHECKED_MARKER)
                    self.tree.item(file_item, tags=('file', 'selected'))
        
        self.status_var.set(f"Auto-selected {len(self.selected_files)} shorter/smaller files for deletion")
    
    def select_all(self):
        """Select all duplicate rows except the first file in each group."""
        self.selected_files.clear()
        selected_count = 0

        for group_item in self.tree.get_children():
            file_items = self.tree.get_children(group_item)
            for index, file_item in enumerate(file_items):
                file_path = self.item_data.get(file_item, {}).get('file_path')
                if not file_path:
                    continue

                if index == 0:
                    self.tree.set(file_item, 'select', UNCHECKED_MARKER)
                    self.tree.item(file_item, tags=('file',))
                    continue

                self.selected_files.add(file_path)
                self.tree.set(file_item, 'select', CHECKED_MARKER)
                self.tree.item(file_item, tags=('file', 'selected'))
                selected_count += 1

        self.status_var.set(f"Selected {selected_count} duplicate files for deletion, keeping the first file in each group")

    def delete_selected(self):
        if not self.selected_files:
            messagebox.showwarning("Warning", "No files selected for deletion.")
            return
        
        file_list = '\n'.join(Path(f).name for f in sorted(self.selected_files)[:MAX_DELETE_PREVIEW_FILES])
        if len(self.selected_files) > MAX_DELETE_PREVIEW_FILES:
            file_list += f'\n... and {len(self.selected_files) - MAX_DELETE_PREVIEW_FILES} more files'
        
        confirm = messagebox.askyesno(
            "Confirm Deletion",
            f"Are you sure you want to delete {len(self.selected_files)} files?\n\n{file_list}\n\n"
            f"A backup list will be created before deletion.\n\n"
            f"This action cannot be undone!",
            icon='warning'
        )
        
        if not confirm:
            return
        
        backup_path = FileOperations.create_backup_list(self.selected_files, self.current_directory)
        if not backup_path:
            messagebox.showerror(
                "Backup Failed",
                "No files were deleted because the backup list could not be created. "
                "Check folder permissions and try again."
            )
            return

        deleted_count, failed_deletions = FileOperations.delete_files(self.selected_files)

        result_msg = f"Successfully deleted {deleted_count} files."
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
        log_info("Deletion complete. Refreshing view...")
        self.scan_duplicates()


# =============================================================================
# Application entry point
# =============================================================================

def main():
    """Launch the Tkinter application."""
    enable_windows_dpi_awareness()
    root = tk.Tk()
    AudioDuplicateDetectorUI(root)
    maximize_window(root)
    root.mainloop()

if __name__ == "__main__":
    main()
