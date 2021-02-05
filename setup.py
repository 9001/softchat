#!/usr/bin/env python3
import os
import sys
import subprocess as sp
from glob import glob
from shutil import rmtree
from setuptools import setup, find_packages, Command


class ST_cmd(Command):
    description = "foo"
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass


class cln(ST_cmd):
    def run(self):
        for d in ["build", "dist", "softchat.egg-info"]:
            try:
                rmtree(d)
            except:
                pass


class tst(ST_cmd):
    def run(self):
        do_rls(False)


class rls(ST_cmd):
    def run(self):
        do_rls(True)


def sh(bin, *args, **kwargs):
    cmd = [bin] + " ".join(args).split(" ")
    print(f"\n\033[1;37;44m{repr(cmd)}\033[0m")
    sp.check_call(cmd, **kwargs)


def do_rls(for_real):
    env = os.environ.copy()
    for ek, tk in [["u", "TWINE_USERNAME"], ["p", "TWINE_PASSWORD"]]:
        v = os.environ.get(ek, "")
        if v:
            env[tk] = v

    py = sys.executable
    sp.run("rem", shell=True)
    try:
        import twine, wheel
    except:
        sh(py, "-m pip install --user twine wheel")

    sh(py, "setup.py cln")
    sh(py, "setup.py sdist bdist_wheel --universal")

    files = glob(os.path.join("dist", "*"))
    dest = "pypi" if for_real else "testpypi"
    sh(py, "-m twine upload -r", dest, *files, env=env)


with open("README.md", encoding="utf8") as f:
    readme = f.read()

a = {}
with open("softchat/__main__.py", encoding="utf8") as f:
    exec(f.read().split("\nimport", 1)[0], a)

a = a["about"]
del a["date"]

a.update(
    {
        "author_email": "@".join([a["name"], "ocv.me"]),
        "python_requires": ">=3.6",
        "install_requires": ["Pillow", "fonttools"],
        "extras_require": {"unkanji": ["fugashi[unidic]"]},
        "entry_points": {"console_scripts": ["softchat=softchat.__main__:main"]},
        "include_package_data": True,
        "long_description": readme,
        "long_description_content_type": "text/markdown",
        "keywords": "youtube chat converter danmaku marquee softsubs ass subtitles",
        "classifiers": [
            "License :: OSI Approved :: MIT License",
            "Development Status :: 3 - Alpha",
            "Environment :: Console",
            "Operating System :: Microsoft :: Windows",
            "Operating System :: POSIX :: Linux",
            "Operating System :: MacOS",
            "Natural Language :: English",
            "Topic :: Multimedia :: Video",
            "Intended Audience :: End Users/Desktop",
            "Programming Language :: Python :: 3",
            "Programming Language :: Python :: 3.6",
            "Programming Language :: Python :: 3.7",
            "Programming Language :: Python :: 3.8",
            "Programming Language :: Python :: 3.9",
        ],
        "packages": find_packages(),
        "cmdclass": {"cln": cln, "rls": rls, "tst": tst},
    }
)

# pprint.pprint(a)
setup(**a)

# c:\Python36\python -m pip install --user -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple softchat
