#! /usr/bin/env python3

"""Statically generates a songbook website (sorted and indexed in multiple ways) from a set of files containing labeled and tagged song lyrics."""

__version__ = "0.1"

import sys
import os
import shutil
import logging
import argparse
import re
import unicodedata
import collections

try:
    import markdown
    import jinja2
except ImportError as error:
    print("ERROR: The required package \"%s\" was not found, please check the installation instructions." % error.name, file=sys.stderr)
    sys.exit(-1)

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
                value = [v.strip() for v in value.split(",") if v.strip()]
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
        self.copyright = self.tags.get("copyright", None)
        self.source = self.tags.get("source", None)
        self.tune = self.tags.get("tune", None)
        self.aka = self.tags.get("aka", [])
        self.see = []
        self.categories = []

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
        return "<Song \"%s\">" % self.title

    def __repr__(self):
        return "<Song \"%s\" (%s)>" % (self.title, self.slug)

    @property
    def slug(self):
        return slugify(self.title) + getattr(self, "uniquing_string", "")


class Category:
    def __init__(self, name):
        self.name = name
        self.songs = []

    def __str__(self):
        return "<Category \"%s\">" % self.name

    def __repr__(self):
        return "<Category \"%s\" (%s)>" % (self.name, self.slug)

    @property
    def slug(self):
        return slugify(self.name)


class SongBook:
    """A collection of songs, linked by their associated categories and cross references."""
    def __init__(self, source_path):
        """Load all song files and templates from source_path.
        
        Song objects are created for all loaded songs, as well as Category objects for any tags they specify.
        The resulting Song and Category objects will then reference each other as appropriate."""
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
        self.songs = self.songs_from_directory(songs_path)
        logging.info("Parsed %d songs", len(self.songs))
        self.link_songs_and_categories()
        self.templates = jinja2.Environment(loader=jinja2.FileSystemLoader(template_path))

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

    def link_songs_and_categories(self):
        """Create categories and make song and category objects refer to each other when referenced by name in tags."""
        songs_by_slug = {}
        # Add all songs by their default title.
        for song in self.songs:
            slug = slugify(song.title)
            if slug not in songs_by_slug:
                songs_by_slug[slug] = []
            songs_by_slug[slug].append(song)
        # Make sure they all have a unique slug.
        for slug, shared_slug_songs in songs_by_slug.items():
            uniquing_number = 2
            for song in shared_slug_songs[1:]:
                while True:
                    song.uniquing_string = "-%d" % uniquing_number
                    uniquing_number += 1
                    if song.slug not in songs_by_slug:
                        break
                logging.info("Multiple songs with the slug \"%s\". \"%s\" is using the slug \"%s\" instead." % (slug, song.title, song.slug))
        # Add songs by any "AKA" titles
        for song in self.songs:
            for alt_title in song.tags.get("aka", []):
                slug = slugify(alt_title)
                if slug not in songs_by_slug:
                    songs_by_slug[slug] = []
                songs_by_slug[slug].append(song)

        # Get all the category names
        category_names = {}
        for song in self.songs:
            for category_name in song.tags.get("tags", []):
                category_slug = slugify(category_name)
                if category_slug not in category_names:
                    category_names[category_slug] = collections.Counter()
                category_names[category_slug][category_name] += 1
        # Create 1 category/slug, w/ most common name.
        self.categories = {}
        for slug, names in category_names.items():
            most_common_name = names.most_common(1)[0][0]
            category = Category(most_common_name)
            self.categories[slug] = category

        # Helper functions for looking up songs/categories.
        def song_for_title(title):
            """Helper to find the matching Song object given a song title.
            
            Song titles may differ slightly (e.g. capitalization, punctuation), as long as they
            have the same slug. If multiple songs have the same slug, go for an exact title match.
            """
            slug = slugify(title)
            if slug not in songs_by_slug:
                return None
            songs = songs_by_slug[slug]
            if len(songs) > 1:
                title_songs = [s for s in songs if title == song.title]
                songs = [s for s in songs if title == song.title or title in song.aka]
                if len(aka_songs) > len(title_songs) >= 1:
                    logging.warning(("Title \"%s\" is the title of a song and the alternate title of a song (AKA: tag).  "
                                                                                    "Only using the direct title.") % title)
                    songs = title_songs
                # TODO: Normalize unicode titles?
                # TODO: Should we check different capitalizations?  Or stick to strict matching if multiple songs share a slug?
            if len(songs) == 0:
                logging.warning("Title \"%s\" has no exact matching song, but multiple songs share the same slug (%s)" % (title, slug))
                return None
            elif len(songs) == 1:
                return songs[0]
            else:
                # TODO: Should we error on duplicate titles here or elsewhere?
                logging.warning("Title \"\" matches two songs.  Picking one arbitrarily." % title)
                return songs[0]

        def category_for_tag(name):
            """Helper to find the matching category given a category name.
            
            Category names can differ slightly (capitalization, punctuation) as long as they have the same slug.
            """
            return self.categories.get(slugify(name), None)

        # Set song.see and song.categories w/ correct referenced objects
        for song in self.songs:
            song.see = []
            for title in song.tags.get("see", []):
                see_song = song_for_title(title)
                if not see_song:
                    logging.info("\"%s\" references song \"%s\" (%s), but no matching song found." % (song.title, title, slugify(title)))
                song.see.append((title, see_song))
            song.categories = []
            for tag in song.tags.get("tags", []):
                category = category_for_tag(tag)
                song.categories.append((tag, category))
                category.songs.append(song)

        logging.info("Songs in %d categories: %s" % (len(self.categories),
                                                     {slug:len(category.songs) for slug, category in self.categories.items()}))
        uncategorized = [song.title for song in self.songs if not song.categories]
        if uncategorized:
            logging.info("%d songs have no categories: %s" % (len(uncategorized), uncategorized))

    def render_templates(self, output_dir):
        """Renders all the templates into output_dir based on our Songs and Categories."""
        created_files = set()
        def render_template(output_path, template_name, **context):
            template = self.templates.get_template(template_name)
            html = template.render(**context)
            with open(os.path.join(output_dir, output_path), 'w') as output_file:
                output_file.write(html)
            created_files.add(output_path)

        songs_dir = "songs"
        categories_dir = "categories"
        for path in ("", songs_dir, categories_dir):
            dir_path = os.path.join(output_dir, path)
            if not os.path.isdir(dir_path):
                os.mkdir(dir_path)
        render_template("songs.html", "songs.html", songbook=self)
        render_template("categories.html", "categories.html", songbook=self)
        for category in self.categories.values():
            render_template(os.path.join(categories_dir, "%s.html" % category.slug), "category.html", songbook=self, category=category)
        for song in self.songs:
            render_template(os.path.join(songs_dir, "%s.html" % song.slug), "song.html", songbook=self, song=song)
        return created_files

    def copy_static(self, static_dir, output_dir):
        """Copy files and their directory structure from static_dir to output_dir.

        Files are copied, as are any directories containing them, but empty directories are excluded, as they would be
        removed by delete_old_files later in the website generation process.
        """
        copied_files = set()
        if not os.path.isdir(static_dir):
            logging.info("No static dir found at \"%s\"." % static_dir)
            return copied_files
        for dirpath, dirnames, filenames in os.walk(static_dir):
            rel_dir = os.path.relpath(dirpath, static_dir)
            if rel_dir == ".":
                rel_dir = ""
            out_dir = os.path.join(output_dir, rel_dir)
            if not os.path.isdir(out_dir) and filenames:
                if os.path.exists(out_dir):
                    os.remove(out_dir)
                os.mkdir(out_dir)
            for filename in filenames:
                src_path = os.path.join(dirpath, filename) 
                out_path = os.path.join(out_dir, filename)
                rel_path = os.path.join(rel_dir, filename)
                if os.path.isdir(out_path):
                    shutils.rmtree(out_path)
                shutil.copy2(src_path, out_path)
                copied_files.add(rel_path)
        return copied_files

    def delete_old_files(self, output_dir, kept_files):
        """Remove contents of output_dir not specified in kept_files.

        output_dir: the directory to clean.
        kept_files: a list of paths relative to output_dir which shouldn't be deleted.

        Files or directories explicitly specified in kept_files aren't deleted,
        incl. any contents.  Any directories containing items in kept_files thus
        aren't deleted, but other items in them may be.
        """
        kept_paths = set() # Files created and files/dirs specified w/ --keep; don't delete (incl. all contents).
        containing_dirs = set() # Dirs containing above; don't delete, but recursively check dir contents.
        for keep_file in kept_files:
            fullpath = os.path.join(output_dir, keep_file)
            if os.path.exists(fullpath):
                kept_paths.add(fullpath)
                parent, _ = os.path.split(keep_file)
                while parent:
                    containing_dirs.add(os.path.join(output_dir, parent))
                    parent, _ = os.path.split(parent)
        for dirpath, dirnames, filenames in os.walk(output_dir):
            dirs_to_check = []
            for subdirname in dirnames:
                subdirpath = os.path.join(dirpath, subdirname)
                if subdirpath in kept_paths:
                    pass # A directory explicitly specified (in --keep), keep w/ all contents.
                elif subdirpath in containing_dirs:
                    dirs_to_check.append(subdirname)
                else:
                    shutil.rmtree(subdirpath)
                    logging.debug("Clearing unused dir. from output dir: \"%s\"" % subdirpath)
            dirnames[:] = dirs_to_check # Only recurse into the directories we don't delete or explicitly keep.
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                if filepath not in kept_paths:
                    os.remove(filepath)
                    logging.debug("Clearing unused file from output dir: \"%s\"" % filepath)


def truncate(string, max_length, suffix='…'):
    """Return a string of at most max_length characters, ending with a particular suffix if truncated."""
    assert max_length > 0, "max_length is not positive: %r" % max_length
    if len(string) <= max_length:
        return string
    if len(suffix) >= max_length:
        return string[:max_length]
    return string[:max_length - len(suffix)] + suffix

def slugify(string):
    """Turns a string into a sluggified version safe for use in URLs.
    
    The resulting slug will only contain lowercase alphanumerics, '_', and '-'.  Strings of other characters
    are converted into a single '-', multiple '-'s will be coalesced, and leading/trailing '-'s are stripped.
    An attempt is made to convert non-ascii characters (e.g. accented letters) to similar ascii characters to
    maintain readability (e.g. "Größe" -> "grosse").
    """
    special_translation = string.lower().translate(str.maketrans({'ø':'o', 'ß':'ss', 'œ':'ae',
                                                    '–':'-','—':'-',
                                                    '”':'"','“':'"','’':"'",'‘':"'"}))
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
    parser.add_argument("--keep", help="Paths (relative to the destination) that shouldn't be cleared even if not overwritten by %(prog)s",
                        action="append", default=[])
    
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
        copied_files = songbook.copy_static(os.path.join(args.source, "static"), args.destination)
        created_files = songbook.render_templates(args.destination)
        for path in copied_files.intersection(created_files):
            logging.warning("File \"%s\" from static was overwritten by a generated file.")
        songbook.delete_old_files(args.destination, set.union(copied_files, created_files, args.keep))
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
