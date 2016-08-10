#! /usr/bin/env python3

"""Statically generates a songbook website (sorted and indexed in multiple ways) from a set of files containing labeled and tagged song lyrics."""

import sys
import os
import logging
import argparse
import re
import unicodedata
try:
    import pystache
    import markdown
except ImportError as error:
    print("ERROR: The required package \"%s\" was not found, please check the installation instructions." % error.name, file=sys.stderr)
    sys.exit(-1)

__version__ = "0.1"
SONG_EXTENSION = ".txt"

class Song:
    """A song with associated metadata."""

    def __init__(self, tags, lyrics, filename=None):
        """Create a Song object given a list of tags and the lyrics.

        tags: a list of key-value pairs.
        lyrics: The lyrics of the song, as a block of Markdown-formatted text.
        filename: Optional, to be used in debugging messages, for missing titles, etc.
        """
        debugging_filename = filename if filename != None else "<no file>"
        self.raw_lyrics = lyrics
        self.lyrics = self.markdown(lyrics)
        self.tags = {}
        single_tags = set(["copyright", "source", "title", "tune"])
        array_tags = set(["aka", "see", "tags"])
        all_tags = single_tags.union(array_tags)
        for key, value in tags:
            tag = key.lower()
            if tag not in all_tags:
                logging.warning("Ignoring unrecognized tag: \"%s\" in file \"%s\"." % (key, debugging_filename))
                continue
            if tag in self.tags:
                logging.warning("Ignoring duplicate tag \"%s\" found in file \"%s\"." % (tag, debugging_filename))
                continue
            if tag in array_tags:
                value = [v.strip() for v in value.split(",")]
            self.tags[tag] = value
        if "title" in self.tags:
            self.title = self.tags["title"]
        else:
            if filename:
                self.title = filename.replace("_", " ")
                if self.title.endswith(SONG_EXTENSION):
                    self.title = self.title[:-len(SONG_EXTENSION)]
            else:
                self.title = "Unknown"
            logging.warning("No title found in file \"%s\".  Falling back on \"%s\"." % (debugging_filename, self.title))

    @classmethod
    def from_string(cls, file_contents, filename=None):
        """Parse the contents of a song file and generate a Song object.
        
        Song files consist of any number of lines containing tags followed by the lyrics of the song.

        A tag line consists of a key separated from it's value by a colon.
        
        All leading and trailing whitespace is stripped from tag's keys and
        values as well as from the lyrics, so the end of tags and the beginning
        of the lyrics can always be triggered by a blank line, even if the
        first line of the lyrics would otherwise be parsed as a tag.
        """
        lines = file_contents.splitlines()
        tags = []
        for index, line in enumerate(lines):
            parts = line.split(':', 1)
            if len(parts) < 2:
                break
            tag = parts[0].strip()
            value = parts[1].strip()
            tags.append((tag, value))
        body = "\n".join(lines[index:]).strip('\n')
        return cls(tags, body, filename)

    _shared_markdown = None
    def markdown(self, text):
        if not Song._shared_markdown:
            Song._shared_markdown = markdown.Markdown(extensions=["markdown.extensions.nl2br", "markdown.extensions.smarty"],
                                                      output_format = "html5")
        return Song._shared_markdown.reset().convert(text)

    def __str__(self):
        tag_lines = ["%s: %s" % tag for tag in self.tags.items()]
        return "%s\n\n%s" % ("\n".join(tag_lines), truncate(self.body, 50))

    def __repr__(self):
        return "Song(tags=%s, body=%s)" % (repr(self.tags), repr(truncate(self.body, 50)))

    def slug(self):
        return slugify(self.title)

    def __getattr__(self, name):
        prefix = "has_tag_"
        if name.startswith(prefix):
            key = name[len(prefix):]
            return key in self.tags and bool(self.tags[key])
        return super().__getattr__(name)


class SongBook:
    def __init__(self, source_path):
        self.source_path = source_path
        songs_path = os.path.join(source_path, "songs")
        template_path = os.path.join(source_path, "templates")
        if not os.path.exists(source_path):
            logging.error("Could not find source directory '%s'" % source_path)
            sys.exit(os.EX_NOINPUT)
        if not os.path.isdir(source_path):
            logging.error("Source '%s' is not a directory" % source_path)
            sys.exit(os.EX_NOINPUT)
        for required_path in (songs_path, template_path):
            if not os.path.isdir(required_path):
                logging.error("Source directory does not contain a %s subdirectory", os.path.split(required_path)[-1])
                sys.exit(os.EX_NOINPUT)
        self.renderer = pystache.Renderer(search_dirs=template_path)
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
                    songs.append(Song.from_string(song_file, filename=filename))
                    # TODO: warn if song title's slug version and filename's slug version aren't the same.
        return songs

    def render_templates(self, path):
        if not os.path.isdir(path):
            os.mkdir(path)
        with open(os.path.join(path, "songs.html"), 'w') as output_file:
            output_file.write(self.renderer.render_name("songs", self))


def truncate(string, max_length, suffix='…'):
    """Return a string of at most max_length characters, ending with a particular suffix if truncated."""
    assert max_length > 0, "max_length is not positive: %r" % max_length
    if len(string) <= max_length:
        return string
    if len(suffix) >= max_length:
        return string[:max_length]
    return string[:max_length - len(suffix)] + suffix

def slugify(string):
    special_translation = string.lower().translate({'ø':'o', 'ß':'ss', 'œ':'ae',
                                                    '–':'-','—':'-',
                                                    '”':'"','“':'"','’':"'",'‘':"'"})
    decomposed = unicodedata.normalize('NFKD', special_translation)
    ascii_only = decomposed.encode('ascii', 'ignore').decode('ascii')
    alphanum = re.sub(r"\W+", "-", ascii_only).strip('-')
    return alphanum

        
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", help="The directory containing songs, templates, etc. (Default: current directory).", default=".")
    parser.add_argument("--destination", help="The directory in which to generate the songbook website (replacing any existing files). "
                        "(Default: a 'site/' directory within the source directory.).")
    parser.add_argument("--version", action="version", version="%%(prog)s %s" % __version__)
    parser.add_argument("-q", "--quiet", help="Quiet mode.  Suppresses non-critical warnings.", action="store_true")
    parser.add_argument("-v", "--verbose", help="Verbose mode. Output debugging messages while running. "
                        "Multiple -v options increase the verbosity, with a maximum of 2.", action="count", default=0)
    
    args = parser.parse_args()
    if not args.destination:
        args.destination = os.path.join(args.source, "site")

    log_level = logging.ERROR if args.quiet else logging.WARNING
    if args.verbose == 1:
        log_level = logging.INFO
    elif args.verbose >= 2:
        log_level = logging.DEBUG
    logging.basicConfig(level=log_level, format="%(levelname)s: %(message)s")

    try:
        songbook = SongBook(args.source)
        songbook.render_templates(args.destination)
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
