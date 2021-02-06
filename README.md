# softchat
* convert twitch/youtube chat into softsubs ([webm](https://ocv.me/dev/softchat.webm))
* supports windows, macos, linux
* MIT-Licensed, 2020-10-12, ed @ irc.rizon.net


# howto

* first-time setup (all recommended steps):

      python3 -m pip install --user softchat chat-downloader fugashi[unidic]
      python3 -m unidic download

* download/convert a youtube VOD automatically with https://ocv.me/dev/?ytdl-tui.py

* ...or do it manually like this:

      python3 -m youtube_dl youtube.com/watch?v=4dlsbJiEa-U
      python3 -m chat_downloader --message_groups all -o same-filename.json youtube.com/watch?v=4dlsbJiEa-U
      python3 -m softchat -m2 same-filename.json

  the json filename should be whatever `youtube-dl` decides to use, except replace the extension with `.json` (and remember quotes depending on OS)

* use `mpv` and resample the FPS to your monitor rate:

      mpv some.mkv --sub-delay=-2 --vf=fps=60
  
  you *may* need to `--vo=direct3d` and *not* fullscreen for resampling to work (see `--vo=help` for more ideas ymmv)


# notes

* superchats will display for 2x the time and with inverted colors

* moderator messages are emphasized  
  (larger outline, and prefixed with a ball)

* mode 1, sidebar chat, creates a huge amount of subtitle events  
  which many media players (including mpv) will struggle with

  for example, seeking will take like 5sec

  you can fix this by muxing the subtitle into the vid:  
  `ffmpeg -i the.webm -i the.ass -c copy muxed.mkv`

* mode 2, danmaku, will look blurry and/or jerky in most players  
  unless you have the subtitles render at your native screen res

  for example in mpv you could add these arguments:  
  `--vo=direct3d --sub-delay=-2 --vf=fps=90`

  replace 90 with your monitor's fps

* after an upgrade, you can reconvert old rips like this:  
  `grep -lE '^Title: .*softchat' -- *.ass | tr '\n' '\0' | xargs -0rtl python3 -m softchat -m2 --`

* youtube VOD chatlogs are incomplete (about 80% of messages are lost)  
  so softchat can now take multiple chat JSONs to splice together:  
  it is recommended to run chat_replay_downloader.py twice,  
  first when the stream is live and then afterwards for the VOD chat;  
  when running softchat, the VOD json should be the first file provided,  
  followed by any live recordings to splice messages from

* on windows, `--kana` requires python 3.8 or newer


# dependencies

* chatrips must be made using https://github.com/xenova/chat-downloader
  * softchat will be updated as the output format of chat-downloader changes

* a copy of `NotoSansCJKjp-Regular.otf` in a folder named `noto-hinted`
  * download here: https://ocv.me/stuff/NotoSansCJKjp-Regular.otf
  * or here: https://noto-website-2.storage.googleapis.com/pkgs/Noto-hinted.zip
  * in the future (tm) softchat will require all the Noto-fonts in this folder

* required python libraries: `Pillow fontTools`

* enable `--kana` (convert kanji to hiragana) with these:

      python3 -m pip install --user fugashi[unidic]
      python3 -m unidic download


# maintainers

* build and release: `python setup.py rls`
