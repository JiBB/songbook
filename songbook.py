#! /usr/bin/env python3

"""Statically generates a songbook website (sorted and indexed in multiple ways) from a set of files containing labeled and tagged song lyrics."""

import sys
import os
import logging
import argparse
import re

__version__ = "0.1"
SONG_EXTENSION = ".txt"

class Song:
    """A song with associated metadata."""

    def __init__(self, tags, body):
        self.tags = tags
        self.body = body

    @classmethod
    def from_string(cls, file_contents):
        """Parses the contents of a song file and generates a Song object
        
        Song files consist of any number of lines containing tags followed by the lyrics of the song.

        A tag line consists of a key separated from it's value by a colon.
        
        All leading and trailing whitespace is stripped from tag's keys and
        values as well as from the lyrics, so the end of tags and the beginning
        of the lyrics can always be triggered by a blank line, even if the
        first line of the lyrics would otherwise be parsed as a tag.
        """
        lines = file_contents.splitlines()
        tags = {}
        body = ""
        for index, line in enumerate(lines):
            parts = line.split(':', 1)
            if len(parts) < 2:
                break
            tag = parts[0].strip()
            value = parts[1].strip()
            tags[tag] = value
        body = "\n".join(lines[index:]).strip('\n')
        return cls(tags, body)


    def __str__(self):
        tag_lines = ["%s: %s" % tag for tag in self.tags.items()]
        return "%s\n\n%s" % ("\n".join(tag_lines), truncate(self.body, 50))

    def __repr__(self):
        return "Song(tags=%s, body=%s)" % (repr(self.tags), repr(truncate(self.body, 50)))

class SongBook:
    def __init__(self, source_path):
        self.source_path = source_path
        songs_path = os.path.join(source_path, "songs")
        if not os.path.exists(source_path):
            logging.error("Could not find source directory '%s'" % source_path)
            sys.exit(os.EX_NOINPUT)
        if not os.path.isdir(source_path):
            logging.error("Source '%s' is not a directory" % source_path)
            sys.exit(os.EX_NOINPUT)
        for required_path in (songs_path,):
            if not os.path.isdir(required_path):
                logging.error("Source directory does not contain a %s subdirectory", os.path.split(required_path)[-1])
                sys.exit(os.EX_NOINPUT)
        self.songs = self.songs_from_directory(songs_path)
        logging.info("Parsed %d songs", len(self.songs))

    def songs_from_directory(self, path):
        """Return an array of Song objects for all song files in a given directory."""
        songs = []
        for filename in os.listdir(path):
            # TODO: Should we recurse into subdirectories?
            filepath = os.path.join(path, filename)
            if os.path.isfile(filepath):
                name, ext = os.path.splitext(filepath)
                if ext == SONG_EXTENSION:
                    song_file = open(filepath).read()
                    songs.append(Song.from_string(song_file))
                    # TODO: warn if song title's slug version and filename's slug version aren't the same.
        return songs


def truncate(string, max_length, suffix='…'):
    """Return a string of at most max_length characters, ending with a particular suffix if truncated."""
    assert max_length > 0, "max_length is not positive: %r" % max_length
    if len(string) <= max_length:
        return string
    if len(suffix) >= max_length:
        return string[:max_length]
    return string[:max_length - len(suffix)] + suffix
        
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", help="The directory containing songs, templates, etc. (Default: current directory).", default=".")
    parser.add_argument("--version", action="version", version="%%(prog)s %s" % __version__)
    parser.add_argument("-q", "--quiet", help="Quiet mode.  Suppresses non-critical warnings.", action="store_true")
    parser.add_argument("-v", "--verbose", help="Verbose mode. Output debugging messages while running. "
                        "Multiple -v options increase the verbosity, with a maximum of 2.", action="count", default=0)
    
    args = parser.parse_args()

    log_level = logging.ERROR if args.quiet else logging.WARNING
    if args.verbose == 1:
        log_level = logging.INFO
    elif args.verbose >= 2:
        log_level = logging.DEBUG
    logging.basicConfig(level=log_level, format="%(levelname)s: %(message)s")

    try:
        songbook = SongBook(args.source)
    except SystemExit:
        pass # We're intentionally exiting, no logging required.
    except KeyboardInterrupt:
        logging.info("Keyboard interrupt, terminating application.")
    except:
        logging.exception("Failed with unhandled exception:")
        raise
    finally:
        logging.shutdown()

if __name__ == "__main__":
    main()
