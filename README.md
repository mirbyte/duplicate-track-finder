# Duplicate Track Finder

Duplicate Track Finder is a standalone desktop app for finding **likely duplicate audio tracks** in a music library by comparing normalized metadata.

It is designed mainly for EDM/DJ libraries, where the same track may appear across radio edits, extended mixes, remix releases, and downloads from different sources.

> **Important:** This app does **not** edit metadata or rename files. It can delete files you select, so always review the results before deleting anything.

*Linux and macOS are currently untested.*

---

## What It Does

Duplicate Track Finder scans a selected folder recursively, reads audio metadata, and groups files that appear to represent the same track.

It compares:

- Track title
- Contributing artist / album artist / composer metadata
- Normalized artist names
- Simplified base title
- File duration, size, quality, and timestamps for review

The app shows likely duplicate groups in a table, lets you compare metadata differences, and provides tools to manually select files for deletion.

---

## How Matching Works

The app normalizes artist metadata by:

- Converting text to lowercase
- Removing accents and common punctuation
- Splitting artist lists on common separators such as commas, semicolons, ampersands, slashes, `feat`, `ft`, `vs`, `and`, and `with`
- Comparing artists as sets instead of raw text strings

It also extracts a simplified base title by removing common version text such as:

- `remix`
- `extended`
- `radio edit`
- `club mix`
- `original mix`
- `vocal mix`
- `instrumental`
- `acoustic`
- Text in parentheses or brackets

Tracks are grouped when their simplified titles match and their normalized artist sets overlap.

Files without usable title and artist metadata are skipped.

---

## Features

- **Metadata-based duplicate detection**  
  Finds likely duplicate tracks using normalized title and artist metadata.

- **Version-aware title matching**  
  Handles common mix/version labels such as extended mixes, edits, remixes, and bracketed release text.

- **Recursive folder scanning**  
  Scans the selected directory and all subdirectories.

- **Parallel metadata processing**  
  Uses multiprocessing to speed up scans on large music libraries.

- **Metadata difference panel**  
  Shows title, artist, album artist, raw artist values, normalized artist values, year, quality, and timestamps for files in a group.

- **Manual selection controls**  
  Double-click files to mark or unmark them for deletion.

- **Auto-select helper**  
  Can automatically keep the longest/largest file in each group and select the others.

- **Deletion backup list**  
  Creates a timestamped text file listing selected files before deletion.

---

## Supported Audio Formats

The app currently scans files with these extensions:

`MP3`, `FLAC`, `WAV`, `M4A`, `OGG`, `AAC`, `WMA`, `OPUS`, `AIFF`, `APE`, `ALAC`

Quality is classified broadly as either **Lossless** or **Lossy** based on file extension.

---

## Requirements

- Python 3.8+
- Tkinter, usually included with Python
- [`tinytag`](https://pypi.org/project/tinytag/)
- [`colorama`](https://pypi.org/project/colorama/)

---

## Installation

Clone or download the repository, then install the required packages:

```bash
python -m pip install tinytag colorama
```

Run the Python version:

```bash
python duplicate_track_finder.py
```

A packaged `.exe` may also be available, but the Python version is recommended for testing and development.

---

## Usage

1. **Select a directory**  
   Click **Browse** and choose the folder containing your audio files.

2. **Scan for duplicates**  
   Click **Scan for Duplicates**. The app searches recursively through subfolders.

3. **Review duplicate groups**  
   Expand each group and compare the title, artist, duration, size, quality, and metadata differences.

4. **Select files for deletion**  
   Double-click a file to toggle whether it should be deleted.

5. **Use auto-select carefully**  
   Click **Auto-Select (Keep Longest/Largest)** to keep the longest/largest file in each group and select the rest.

6. **Delete selected files**  
   Press **Delete** or click **Delete Selected Files**. The app creates a text list of selected files before deleting them.

---

## Safety Notes

This tool is designed to help you review duplicates, not to make perfect decisions automatically.

Before deleting files:

- Review every selected group manually.
- Back up your music library if the files matter to you.
- Pay extra attention to live versions, remasters, clean/explicit versions, and different mixes.
- Remember that the app creates a text list of deleted files, not a backup copy of the audio files.

Deletion uses normal file removal, so deleted files may not be recoverable.

---

## Known Limitations

- Files without usable title and artist metadata are skipped.
- Matching is optimized for EDM/DJ libraries and may be less accurate for other genres.
- Different versions of the same song may be grouped together if their version labels are removed during title normalization.
- Unicode and metadata handling may vary depending on how tags are encoded.
- Linux and macOS behavior has not been tested.

---

## Technical Details

- **GUI:** Tkinter with ttk widgets
- **Metadata:** TinyTag
- **Concurrency:** `ProcessPoolExecutor`
- **Primary platform:** Windows 11
- **Debug mode:** Set `DUPLICATE_TRACK_FINDER_DEBUG=1` to enable debug logging

---

## Disclaimer

Duplicate Track Finder may produce false positives. Use it at your own risk.

The app does **not** create backups of audio files. It only creates a timestamped text file listing the files selected for deletion.

<br>

![finderss](https://github.com/user-attachments/assets/e2311180-10ec-438a-8608-ca3da6d80ce9)
