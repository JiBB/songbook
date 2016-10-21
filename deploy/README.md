# Automatically Deploy to GitHub Pages

If your Songbook project is stored in a git repository and you want to host the generated website as a [GitHub Project Page](https://pages.github.com), you can use [Travis CI](https://travis-ci.org) to automatically regenerate and deploy the site whenever you commit any changes to it.  The [example project](https://jibb.github.io/songbook) included in this repository is automatically deployed in such a fashion.  However, the configuration used is slightly different, as it is located in the same repository as the songbook.py application itself.  However, the [example.travis.yml](example.travis.yml) file included here shows how to set up continuous deployments in your own repository.

## Requirements

* A songbook project (`songs`, `static` and `templates` directories) located in a git repository hosted at [GitHub](https://github.com).
* An account with [Travis CI](https://travis-ci.org) ( or a [paid account](https://travis-ci.com) if your project is in a private repository) linked to your GitHub account, and enabled for your repository.
* The [travis](https://github.com/travis-ci/travis.rb#installation) command line tools installed.

## Setup

### Deployment credentials

To give Travis permission to push the builds to the `gh-pages` branch of your repository, you'll set up a repository-specific deploy key with GitHub, which will be encrypted and stored by Travis.  First, generate a brand new SSH key.  Add the public key as a Deploy Key to your GitHub repository (at `https://github.com/<username>/<repository>/settings/keys`).  Copy the private key to your git repository, run `travis encrypt-file <deploy_key>` to generate the encrypted version `<deploy_key>.enc` (you can now delete `<deploy_key>`, with the appropriate keys available when Travis is running.  Make note of the encryption label (the hex string like `0a6446eb3ae3` in `$encrypted_0a6446eb3ae3_key` from the output, but otherwise ignore it.  Commit `<deploy_key>.enc` to your repository, but make sure _not_ to commit `<deploy_key>`.

### Configuration

Copy `example.travis.yml` to the root of your repository and rename it `.travis.yml`.  You will need to update the `env` section to include your email, the location and name of your deploy key inyour repository (minus the `.enc`), and the encryption label you made note of above.

You can also change the timezone exported in `before_install`, so any timestamps included in your site will be correct.

The configuration file is set up for sites served from `http://<user>.github.io/<repository>/`, so the script is passed your repository's name as a base url (what the feature was developed for).  However, if you've set up a [custom domain](https://help.github.com/articles/adding-or-removing-a-custom-domain-for-your-github-pages-site/) for your project page, you'll need to follow the instructions in the comments and remove `--base \"$(basename $(pwd))\"` from the invocation of songbook.py.

### Done

Once you've committed the `<deploy_key>.enc` file and the customized `.travis.yml` file to your repository (and turned on Travis for your repository), it should automatically build and deploy, creating an orphan gh-pages branch if none exists, and should update again each time you commit and push changes to your project.

## Acknowledgements

This configuration is strongly based on [Domenic Denicola's instructions](https://gist.github.com/domenic/ec8b0fc8ab45f39403dd) on using Travis and gh-pages together.

