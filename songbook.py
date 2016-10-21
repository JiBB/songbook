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
import http.server
import posixpath
import urllib
import datetime
import time
import subprocess

try:
    import markdown
    import jinja2
except ImportError as error:
    logging.error(" The required package \"%s\" was not found, please check the installation instructions." % error.name)
    sys.exit(-1)

SONG_EXTENSION = ".txt"


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

    __bold_re = re.compile(r"(?:\*\*(.+?)\*\*)|(?:__(.+?)__)")
    __italic_re = re.compile(r"(?:\*(.+?)\*)|(?:_(.+?)_)")
    __unicode_alphanum_re = re.compile(r"\w", re.UNICODE)
    @property
    def first_line(self):
        try:
            return self._first_line
        except:
            for line in self.raw_lyrics.splitlines():
                line = Song.__bold_re.sub("", line)
                line = self.__italic_re.sub("", line)
                line = line.strip()
                if Song.__unicode_alphanum_re.search(line):
                    return line
        return "[%s]" % self.title


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
    def __init__(self, songs_path):
        """Load all song files and templates from source_path.
        
        Song objects are created for all loaded songs, as well as Category objects for any tags they specify.
        The resulting Song and Category objects will then reference each other as appropriate."""
        self.songs = self.songs_from_directory(songs_path)
        logging.info("Parsed %d songs", len(self.songs))
        self.link_songs_and_categories()

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
        self.categories = []
        categories_by_slug = {}
        for slug, names in category_names.items():
            most_common_name = names.most_common(1)[0][0]
            category = Category(most_common_name)
            self.categories.append(category)
            categories_by_slug[slug] = category

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
            return categories_by_slug.get(slugify(name), None)

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


class SiteBuilder:
    """Create a static website based on song files and templates read in."""
    def __init__(self, source, destination, keep, base_path):
        self.source = source
        self.destination = destination
        self.keep = keep
        self.base_path = base_path

        self.songs_path = os.path.join(self.source, "songs")
        self.templates_path = os.path.join(self.source, "templates")
        self.static_path = os.path.join(self.source, "static")
        if not os.path.exists(self.source):
            logging.error("Could not find source directory '%s'" % source_path)
            sys.exit(os.EX_NOINPUT)
        if not os.path.isdir(self.source):
            logging.error("Source '%s' is not a directory" % source_path)
            sys.exit(os.EX_NOINPUT)
        for required_path in (self.songs_path, self.templates_path):
            if not os.path.isdir(required_path):
                logging.error("Source directory does not contain a %s subdirectory" % os.path.basename(required_path))
                sys.exit(os.EX_NOINPUT)
        self.templates = jinja2.Environment(loader=jinja2.FileSystemLoader(self.templates_path))
        self.templates.filters['datetimeformat'] = lambda value, format='%B %d, %Y, %-I:%M %p': value.strftime(format)
        self.copied_files = set()
        self.generated_files = set()
        self.gather_metadata()

    def gather_metadata(self):
        self.metadata = {}
        self.metadata["date"] = datetime.datetime.now()
        self.metadata["version"] = __version__
        # Gather # of parent commits, branch, sha, etc. from git repo (if present)
        try:
            common_args = {"cwd": self.source, "stderr": subprocess.DEVNULL}
            version = subprocess.check_output(["git", "rev-list", "HEAD", "--count"], **common_args).decode('utf-8').strip()
            sha     = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], **common_args).decode('utf-8').strip()
            try:
                branch  = subprocess.check_output(["git", "symbolic-ref", "--short", "-q", "HEAD"], **common_args).decode('utf-8').strip()
            except subprocess.CalledProcessError as error:
                branch = "detached-HEAD"
            # Opt. override, e.g. for a CI that always gets a detached head (GIT_BRANCH=$TRAVIS_BRANCH).
            branch = os.getenv("GIT_BRANCH", branch)
            dirty   = subprocess.run(["git", "diff-index", "--quiet", "HEAD", "--"], stdout=subprocess.DEVNULL, **common_args).returncode
            long_version = version
            if branch != "master":
                long_version += "-" + branch
            if dirty:
                long_version += " (dirty)"
            self.metadata["git"] = {}
            self.metadata["git"]["version"] = version
            self.metadata["git"]["long_version"] = long_version
            self.metadata["git"]["sha"] = sha
        except subprocess.CalledProcessError as error:
            logging.info("Source directory is not (in) a git repository; no version info found.")
            return
        except OSError as error:
            logging.warning("Can't run git to check for version information")
            return

    def build_site(self):
        self.songbook = SongBook(self.songs_path)
        self.copy_static()
        self.render_templates()
        for path in set.intersection(self.copied_files, self.created_files):
            logging.warning("File \"%s\" from static was overwritten by a generated file." % path)
        self.delete_old_files()

    def render_templates(self):
        """Renders all the templates into destination directory based on our Songs and Categories."""
        self.created_files = set()
        def mkdir_f(dir_path):
            """Forcibly create a directory at dir_path, removing any file there, and with no error for existing directories."""
            if not os.path.isdir(dir_path):
                if os.path.exists(dir_path):
                    os.remove(dir_path)
                os.mkdir(dir_path)
        def mkdir_f_p(dir_path):
            """Forcibly create a directory at dir_path, (and all parent directories that don't exist, up to self.destination)."""
            if dir_path == "":
                dir_path = os.path.curdir
            rel_path = os.path.relpath(dir_path, self.destination)
            if rel_path.startswith(os.path.pardir+os.path.sep):
                return
            head, tail = os.path.split(rel_path)
            if head:
               mkdir_f_p(os.path.join(self.destination, head))
            else:
                mkdir_f(self.destination)
            mkdir_f(dir_path)
        def render_template(output_path, template_name, optional=False, **context):
            output_filename = os.path.join(output_path, "index.html")
            try:
                try:
                    template = self.templates.get_template(template_name)
                except jinja2.exceptions.TemplateNotFound as exception:
                    if optional:
                        logging.debug("Optional template not found: {0.message}".format(exception))
                        return
                    else:
                        logging.error("Required template not found: {0.message}".format(exception))
                        sys.exit(os.EX_NOINPUT)
                try:
                    url = posixpath.sep + (output_path + posixpath.sep if output_path else "")
                    html = template.render(metadata=self.metadata, songbook=self.songbook, base_path=self.base_path, url=url, **context)
                except jinja2.exceptions.TemplateNotFound as exception:
                    logging.error("Referenced template not found: {0.message}".format(exception))
                    sys.exit(os.EX_DATAERR)
            except jinja2.exceptions.TemplateSyntaxError as exception:
                exception.translated = False # Since we're skipping the information translated into the traceback...
                logging.error("Error rendering template '{0}':\n  {1}".format(template_name, exception))
                sys.exit(os.EX_DATAERR)
            full_output_path = os.path.join(self.destination, output_filename)
            mkdir_f_p(os.path.dirname(full_output_path))
            if os.path.isdir(full_output_path):
                shutils.rmtree(full_output_path)
            with open(full_output_path, 'w') as output_file:
                output_file.write(html)
            self.created_files.add(output_filename)

        songs_dir = "songs"
        categories_dir = "categories"
        render_template("", "index.html")
        render_template("songs", "songs.html")
        render_template("categories", "categories.html")
        for category in self.songbook.categories:
            render_template(os.path.join(categories_dir, "%s" % category.slug), "category.html", category=category)
        for song in self.songbook.songs:
            render_template(os.path.join(songs_dir, "%s" % song.slug), "song.html", song=song)
        render_template("about", "about.html", optional=True)
        render_template("bytitle", "bytitle.html", optional=True)
        render_template("bycategory", "bycategory.html", optional=True)
        render_template("firstlines", "firstlines.html", optional=True)

    def copy_static(self):
        """Copy files and their directory structure from static directory to the output directory.

        Files are copied, as are any directories containing them, but empty directories are excluded, as they would be
        removed by delete_old_files later in the website generation process.
        """
        self.copied_files = set()
        if not os.path.isdir(self.static_path):
            logging.info("No static dir found at \"%s\"." % self.static_path)
            return
        for dirpath, dirnames, filenames in os.walk(self.static_path):
            rel_dir = os.path.relpath(dirpath, self.static_path)
            if rel_dir == os.path.curdir:
                rel_dir = ""
            out_dir = os.path.join(self.destination, rel_dir)
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
                self.copied_files.add(rel_path)

    def delete_old_files(self):
        """Remove contents of self.destination not created, copied in, or specified in self.keep.

        kept_files is the union of self.copied_files, self.created_files, and self.keep.
        Each of these should be a list of paths relative to self.destination which shouldn't be deleted.

        Files or directories explicitly specified in kept_files aren't deleted,
        incl. any contents.  Any directories containing items in kept_files thus
        aren't deleted, but other items in them may be.
        """
        kept_files = set.union(self.copied_files, self.created_files, self.keep)
        kept_paths = set() # Files created and files/dirs specified w/ --keep; don't delete (incl. all contents).
        containing_dirs = set() # Dirs containing above; don't delete, but recursively check dir contents.
        for keep_file in kept_files:
            fullpath = os.path.join(self.destination, keep_file)
            if os.path.exists(fullpath):
                kept_paths.add(fullpath)
                parent = os.path.dirname(keep_file)
                while parent:
                    containing_dirs.add(os.path.join(self.destination, parent))
                    parent = os.path.dirname(parent)
        for dirpath, dirnames, filenames in os.walk(self.destination):
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

    def observed_event(self, event):
        assert(not event.is_directory)
        # Handle moved files/dirs as a pair of creation/deletion.
        # This lets us deal with files moved from one special dir to another w/o complication
        if event.event_type == "moved" and not event.is_directory:
            logging.debug(event)
            self.observed_event(watchdog.events.FileDeletedEvent(event.src_path))
            self.observed_event(watchdog.events.FileCreatedEvent(event.dest_path))
            return

        def in_path(event, path):
            return not os.path.relpath(event.src_path, path).startswith(os.path.pardir+os.path.sep)
        if in_path(event, self.songs_path):
            logging.debug(event)
            logging.info("Songs changed, re-loading and re-rendering.")
            self.songbook = SongBook(self.songs_path)
            self.render_templates()
            self.delete_old_files()
        elif in_path(event, self.templates_path):
            logging.debug(event)
            logging.info("Templates changed, re-rendering.")
            self.render_templates()
            self.delete_old_files()
        elif in_path(event, self.static_path):
            logging.debug(event)
            rel_path = os.path.relpath(event.src_path, self.static_path)
            out_path = os.path.join(self.destination, rel_path)
            try:
                if event.event_type == "created" and rel_path in self.created_files:
                    logging.warning("File \"%s\" from static is shaddowed by a generated file." % rel_path)
                elif event.event_type in ("created", "modified"):
                    logging.info("Static file %s, copying '%s'" % (event.event_type, rel_path))
                    os.makedirs(os.path.dirname(out_path), exist_ok=True)
                    if os.path.isdir(out_path):
                        shutils.rmtree(out_path)
                    shutil.copy2(event.src_path, out_path)
                    self.copied_files.add(rel_path)
                elif event.event_type in ("deleted",):
                    logging.info("Static file deleted, removing '%s'" % rel_path)
                    os.remove(out_path)
                    self.copied_files.remove(rel_path)
                else:
                    logging.error("Unknown event type: '%s'" % event.event_type)
            except FileNotFoundError as error:
                logging.debug("File '%s' removed before processing" % error.filename)


class Server:
    """A basic HTTP server that serves documents from a specific document root, not just the current directory."""
    def __init__(self, document_root, port=8000, base=None):
        class RootedHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
            def translate_path(self, path):
                """Translates a URL path to be a local filesystem path rooted at self.root_directory.

                Based on the SimpleHTTPRequestHandler implementation, but modified for a different root.
                """
                path = posixpath.normpath(urllib.parse.unquote(path))
                if base:
                    if path.startswith(base + posixpath.sep):
                        path = path[len(base):]
                    elif path == base:
                        path = posixpath.sep
                    else:
                        self.send_error(403, "Only serving files under '%s'" % base)
                        return "/dev/null/nonexistant" # Hack to make opening the path fail.
                words = path.split('/')
                words = filter(None, words)
                path = document_root
                for word in words:
                    drive, word = os.path.splitdrive(word)
                    head, word = os.path.split(word)
                    if word in (os.curdir, os.pardir):
                        continue
                    path = os.path.join(path, word)
                return path

            def log_message(self, format, *args):
                """Log an arbitrary message, modified to use our logging levels and a more compact format."""
                logging.info("- [%s] %s" % (self.log_date_time_string(), format%args))

            def log_date_time_string(self):
                """Return the current time formatted for logging.  Modified to be more compact."""
                now = time.time()
                year, month, day, hh, mm, ss, x, y, z = time.localtime(now)
                return "%02d:%02d:%02d" % (hh, mm, ss)

        self.httpd = http.server.HTTPServer(("", port), RootedHTTPRequestHandler)
        self.port = self.httpd.socket.getsockname()[1]
    
    def serve(self):
        self.httpd.serve_forever()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", help="The directory containing songs, templates, etc. (Default: current directory).", default=os.path.curdir)
    parser.add_argument("--destination", help="The directory in which to generate the songbook website (replacing any existing files). "
                        "(Default: a 'site/' directory within the source directory.).")
    parser.add_argument("--version", action="version", version="%%(prog)s %s" % __version__)
    log_args = parser.add_mutually_exclusive_group()
    log_args.add_argument("-q", "--quiet", help="Quiet mode.  Suppresses non-critical warnings.", action="store_true")
    log_args.add_argument("-v", "--verbose", help="Verbose mode. Output debugging messages while running. "
                        "Multiple -v options increase the verbosity, with a maximum of 2.", action="count", default=0)
    parser.add_argument("--keep", help="Paths (relative to the destination) that shouldn't be cleared even if not overwritten by %(prog)s",
                        action="append", default=[])

    parser.add_argument("--base", help="A directory from which the website expects to be served.  Provided for inclusion in "
                        "templates as well as used when serving the website for testing.", default=posixpath.sep)
    parser.add_argument("--serve", help="Start a basic webserver for testing after building, default port is %(const)d.  Implies --watch.",
                        dest="port", type=int, const=8000, nargs="?", default=None)
    watch_args = parser.add_mutually_exclusive_group()
    watch_args.add_argument("-w", "--watch", help="Watch the source directory for changes, rebuilding the site when they occur.",
                            action="store_true", default=None)
    watch_args.add_argument("--no-watch", help="Disable the watching implied by --serve", dest="watch", action="store_false", default=None)

    args = parser.parse_args()
    if not args.destination:
        args.destination = os.path.join(args.source, "site")
    # If serving the created site, turn on watching unless explicitly disabled.
    if args.port != None and args.watch != False:
        args.watch = True
    args.base = args.base.strip(posixpath.sep)
    if args.base:
        args.base = posixpath.sep + args.base
    else:
        args.base = None

    log_level = logging.ERROR if args.quiet else logging.WARNING
    if args.verbose == 1:
        log_level = logging.INFO
    elif args.verbose >= 2:
        log_level = logging.DEBUG
    logging.basicConfig(level=log_level, format="%(levelname)s: %(message)s")
    logging.getLogger('MARKDOWN').setLevel(logging.WARNING)

    if args.watch:
        try:
            global watchdog
            import watchdog
            import watchdog.observers
            import watchdog.events
        except ImportError as error:
            logging.warning("Watching for changes requires the 'watchdog' module; lease check the installation instructions. "\
                            "Disabling watching until module is installed (or use --nowatch to avoid this warning)")
            args.watch = False

    observer = None
    try:
        site_builder = SiteBuilder(args.source, args.destination, args.keep, args.base)
        site_builder.build_site()

        if args.watch:
            logging.warning("Watching for changes and regenerating site.%s" % ("  ^C to kill..." if args.port == None else ""))
            event_handler = watchdog.events.PatternMatchingEventHandler(ignore_patterns=["*/.DS_Store", "*/Thumbs.db", "*.swp", "*.swo", "*~"], ignore_directories=True)
            event_handler.on_any_event = site_builder.observed_event
            observer = watchdog.observers.Observer()
            observer.schedule(event_handler, args.source, recursive=True)
            observer.start()

        if args.port != None:
            server = Server(args.destination, args.port, base=args.base)
            logging.warning("Starting webserver on port %d.  ^C to kill..." % server.port)
            server.serve()
        elif args.watch:
            # If we're watching for changes, but not serving, keep main thread busy with something.
            while True:
                time.sleep(1)
    except SystemExit:
        raise
    except KeyboardInterrupt:
        logging.info("Keyboard interrupt, terminating application.")
    except:
        logging.exception("Failed with unhandled exception:")
        raise
    finally:
        if observer:
            observer.stop()
            observer.join()
        logging.shutdown()

if __name__ == "__main__":
    main()
