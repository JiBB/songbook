# Songbook

Statically generates a songbook website (sorted and indexed in multiple ways) from a set of files containing labeled and tagged song lyrics.


## Getting Started

### Prerequisities

Songbook requires Python 3, as well as the following packages:

* [Jinja2](http://jinja.pocoo.org)
* [Markdown](http://pythonhosted.org/Markdown/)

### Installing

It can be cleanest to install all the required packages in their own virtual environment (showing the activation script for bash):

```
pyvenv venv
source venv/bin/activate
```

Then use pip to install the required libraries:

```
pip3 install jinja2
pip3 install Markdown
```

For a test, try running Songbook on the provided example data:

```
./songbook.py --source Example
```


## How To Use

### Source Files

In the directory you run SongBook in/on, it expects to find several files and directories of content:

#### songs

The `songs` directory is required, and contains one file for each song to be featured in the final website.  Each song file consists  of any number of lines containing tags followed by the lyrics of the song.

A tag line consists of a key separated from it's value by a colon.  All leading and trailing whitespace is stripped from tag's keys and  values as well as from the lyrics, so the end of tags and the beginning of the lyrics can always be triggered by a blank line, even if the first line of the lyrics would otherwise be parsed as a tag (contains a `:`).

The following tags are currently supported:

* `Title:` The title of the song.
* `AKA:` A comma separated list of alternate titles for the song.
* `See:` A comma separated list of the titles of related songs ("See Also")
* `Tags:` A comma separated list of categories into which the song falls.
* `Source:` A description of who wrote the song.
* `Copyright:` Copyright information for non-public-domain songs.

The lyrics of the song are interpreted as [Markdown](http://daringfireball.net/projects/markdown/syntax)-formatted text, with the extension that single line-breaks remain as `<br>` tags in the output (while double line-breaks still make new paragraphs), making it easier to correctly format lyrics.  For example, this:

```Markdown
A silly _song_,
With **crazy** lyrics.

It's got two [verses]!

* A list
* of variations.
```

becomes:

>A silly _song_,
>With **crazy** lyrics.
>
>It's got two verses!
>
>* A list
>* of variations.

#### templates

The `templates` directory is required, and contains template files into which the songs and their tags are inserted when rendered.  These template files are html code with [Jinja](http://jinja.pocoo.org/docs/dev/templates/) templating system commands in them which will be expanded using the data from the songs parsed out of the `songs` directory.

The required templates are:

* `songs.html` — Rendered to `songs.html` in the final website, to contain all the songs in alphabetical order by title.

Other templates in the directory will not be used directly, but can be used with the processed templates through [template inheritance](http://jinja.pocoo.org/docs/dev/templates/#template-inheritance) for content common to multiple templates. (E.g. the `common.html` template in the Example Songbook directory that other templates inherit from.)


### Running SongBook

To create a song book website based on the current folder, storing the output into the directory `site` within the source (current) directory:

```
songbook
```

Or specify the path to the source, storing the output into the directory `site` within the source directory:

```
songbook --source <source>
```

Or specify paths to the source and destination directory:

```
songbook --source <source> --destination <destination>
```


## Authors

* **Jonathan Beall**—[JiBB](https://github.com/JiBB)


## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details
