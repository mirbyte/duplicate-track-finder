# Duplicate Track Finder
A Windows desktop application for detecting and managing duplicate music tracks based on metadata comparison, specifically designed for EDM libraries. This application **cannot** modify metadata or filenames.

*Linux/macOS untested!*

## How It Works

The application normalizes artist metadata by handling various delimiters (semicolons, commas, ampersands, "feat", "ft", "vs", "and", slashes), removing accents and special characters, converting to lowercase, and creating sets for comparison. Base titles are extracted by removing version information like "remix", "extended", "radio edit", "club mix", "original mix", "vocal mix", "instrumental", "acoustic", and content in parentheses/brackets. Tracks are grouped as duplicates when base titles match exactly AND artists have at least one artist in common or one artist set is a subset of the other. If the files don't contain proper metadata, they are skipped completely.


## Features

- **Intelligent Track Detection** - Identifies duplicate tracks by comparing normalized artist names and base titles, even when different versions exist (remixes, extended mixes, radio edits).

- **Version-Aware Matching** - Removes version information (remix, extended, radio edit, club mix, etc.) and content in parentheses/brackets to identify the same track across different releases.

- **Multi-threaded Processing** - Leverages multiprocessing for fast metadata extraction from large music collections.

- **Metadata Comparison** - Side-by-side comparison of track metadata including contributing artists, album artist, title, duration, quality, and timestamps.

- **Smart Auto-Selection** - Automatically selects shorter/smaller duplicates for deletion while keeping the highest quality version (longest duration + largest file size).

## Supported Audio Formats

**`MP3`**
**`FLAC`**
**`WAV`**


## Requirements

Python 3.7+ with the following dependencies:

```
tkinter (usually included with Python)
tinytag
colorama
```


## Installation

Install required packages:

```bash
pip install tinytag colorama
```

Clone or download the repository, then run the .py or .exe (python version recommended)


## Usage

**Select Directory** - Click "Browse" to choose the folder containing audio files (searches recursively through subdirectories).

**Scan for Duplicates** - Click "Scan for Duplicates" to analyze all audio files using metadata.

**Review Groups** - Duplicate track groups are displayed hierarchically with metadata columns showing title, contributing artists, length, size, and quality.

**Select Files** - Double-click files to toggle selection for deletion, or use "Auto-Select" to keep longest/largest versions.

**Delete** - Press Delete key or click "Delete Selected Files" to remove duplicates (backup list is automatically created).


## Known Issues

This application may contain bugs as it is shared for community use and further development. Unicode character handling may vary across different metadata encodings. Detection logic is optimized for EDM/DJ libraries and may require adjustment for other genres. The application is primarily tested on Windows 11.

## Technical Details

**GUI Framework** - Tkinter with ttk styling

**Metadata Library** - TinyTag for audio file metadata extraction

**Concurrency** - ProcessPoolExecutor for parallel file processing


## Disclaimer

This tool is not perfect and may contain bugs. Use at your own risk and always review selections before deleting files. **It does not create backups**, only a text file that includes the names of the removed files!

<br>


![finderss](https://github.com/user-attachments/assets/e2311180-10ec-438a-8608-ca3da6d80ce9)




