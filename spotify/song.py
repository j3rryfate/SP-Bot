import datetime
import os
import time  # Added to fix NameError

import requests
from telethon.tl import types
from telethon.tl.types import PeerUser
from youtube_search import YoutubeSearch
import yt_dlp
import eyed3.id3
import eyed3
from telethon import Button, events

from consts import DOWNLOADING, UPLOADING, PROCESSING, ALREADY_IN_DB, NO_LYRICS_FOUND, SONG_NOT_FOUND
from models import session, User, SongRequest
from spotify import SPOTIFY, GENIUS
from telegram import DB_CHANNEL_ID, CLIENT, BOT_ID

if not os.path.exists('covers'):
    os.makedirs('covers')
if not os.path.exists('songs'):
    os.makedirs('songs')


class Song:
    def __init__(self, link):
        self.spotify = SPOTIFY.track(link)
        self.id = self.spotify['id']
        self.spotify_link = self.spotify['external_urls']['spotify']
        self.track_name = self.spotify['name']
        self.artists_list = self.spotify['artists']
        self.artist_name = self.artists_list[0]['name']
        self.artists = self.spotify['artists']
        self.track_number = self.spotify['track_number']
        self.album = self.spotify['album']
        self.album_id = self.album['id']
        self.album_name = self.album['name']
        self.release_date = int(self.spotify['album']['release_date'][:4])
        self.duration = int(self.spotify['duration_ms'])
        self.duration_to_seconds = int(self.duration / 1000)
        self.album_cover = self.spotify['album']['images'][0]['url']
        self.path = f'songs'
        self.file = f'{self.path}/{self.id}.mp3'
        self.uri = self.spotify['uri']

    def features(self):
        if len(self.artists) > 1:
            features = "(Ft."
            for artistPlace in range(0, len(self.artists)):
                try:
                    if artistPlace < len(self.artists) - 2:
                        artistft = self.artists[artistPlace + 1]['name'] + ", "
                    else:
                        artistft = self.artists[artistPlace + 1]['name'] + ")"
                    features += artistft
                except:
                    pass
        else:
            features = ""
        return features

    def convert_time_duration(self):
        target_datetime_ms = self.duration
        base_datetime = datetime.datetime(1900, 1, 1)
        delta = datetime.timedelta(0, 0, 0, target_datetime_ms)

        return base_datetime + delta

    def download_song_cover(self):
        response = requests.get(self.album_cover)
        image_file_name = f'covers/{self.id}.png'
        image = open(image_file_name, "wb")
        image.write(response.content)
        image.close()
        return image_file_name

    def yt_link(self):
        results = list(YoutubeSearch(str(self.track_name + " " + self.artist_name)).to_dict())
        time_duration = self.convert_time_duration()
        yt_url = None

        for yt in results:
            yt_time = yt["duration"]
            yt_time = datetime.datetime.strptime(yt_time, '%M:%S')
            difference = abs((yt_time - time_duration).total_seconds())

            if difference <= 3:
                yt_url = yt['url_suffix']
                break
        if yt_url is None:
            return None

        yt_link = str("https://www.youtube.com/" + yt_url)
        return yt_link

    def yt_download(self, yt_link=None):
        options = {
            # PERMANENT options
            'format': 'bestaudio/best',
            'keepvideo': True,
            'outtmpl': f'{self.path}/{self.id}',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320'
            }],
        }
        if yt_link is None:
            yt_link = self.yt_link()
        with yt_dlp.YoutubeDL(options) as mp3:
            mp3.download([yt_link])

    def lyrics(self):
        try:
            return GENIUS.search_song(self.track_name, self.artist_name).lyrics
        except:
            return None

    def song_meta_data(self):
        mp3 = eyed3.load(self.file)
        mp3.tag.artist_name = self.artist_name
        mp3.tag.album_name = self.album_name
        mp3.tag.album_artist = self.artist_name
        mp3.tag.title = self.track_name + self.features()
        mp3.tag.track_num = self.track_number
        mp3.tag.year = self.release_date  # Fixed to use release_date instead of track_number

        lyrics = self.lyrics()
        if lyrics is not None:
            mp3.tag.lyrics.set(lyrics)

        mp3.tag.images.set(3, open(self.download_song_cover(), 'rb').read(), 'image/png')
        mp3.tag.save()

    def download(self, yt_link=None):
        if os.path.exists(self.file):
            print(f'[SPOTIFY] Song Already Downloaded: {self.track_name} by {self.artist_name}')
            return self.file
        print(f'[YOUTUBE] Downloading {self.track_name} by {self.artist_name}...')
        self.yt_download(yt_link=yt_link)
        print(f'[SPOTIFY] Song Metadata: {self.track_name} by {self.artist_name}')
        self.song_meta_data()
        print(f'[SPOTIFY] Song Downloaded: {self.track_name} by {self.artist_name}')
        return self.file

    async def song_telethon_template(self):
        message = f'''
🎧 Title :`{self.track_name}`
🎤 Artist : `{self.artist_name}{self.features()}`
💿 Album : `{self.album_name}`
📅 Release Date : `{self.release_date}`

[IMAGE]({self.album_cover})
{self.uri}   
        '''

        buttons = [[Button.inline(f'📩Download Track!', data=f"download_song:{self.id}")],
                   [Button.inline(f'🖼️Download Track Image!', data=f"download_song_image:{self.id}")],
                   [Button.inline(f'👀View Track Album!', data=f"album:{self.album_id}")],
                   [Button.inline(f'🧑‍🎨View Track Artists!', data=f"track_artist:{self.id}")],
                   [Button.inline(f'📃View Track Lyrics!', data=f"track_lyrics:{self.id}")],
                   [Button.url(f'🎵Listen on Spotify', self.spotify_link)],
                   ]

        return message, self.album_cover, buttons

    async def artist_buttons_telethon_templates(self):
        message = f"{self.track_name} track Artist's"
        buttons = [[Button.inline(artist['name'], data=f"artist:{artist['id']}")]
                   for artist in self.artists_list]
        return message, buttons

    def save_db(self, user_id: int, song_id_in_group: int):
        user = session.query(User).filter_by(telegram_id=user_id).first()
        if not user:
            user = User(telegram_id=user_id)
            session.add(user)
            session.commit()
        session.add(SongRequest(
            spotify_id=self.id,
            user_id=user.id,
            song_id_in_group=song_id_in_group,
            group_id=DB_CHANNEL_ID
        ))
        session.commit()

    @staticmethod
    async def progress_callback(processing, sent_bytes, total):
        percentage = sent_bytes / total * 100
        await processing.edit(f"Uploading: {percentage:.2f}%")

    @staticmethod
    async def upload_on_telegram(event: events.CallbackQuery.Event, song_id):
        processing = await event.respond(PROCESSING)

        # Check if the song is already in the database
        song_db = session.query(SongRequest).filter_by(spotify_id=song_id).first()
        if song_db:
            message_id = song_db.song_id_in_group
            await CLIENT.forward_messages(
                entity=event.chat_id,
                messages=message_id,
                from_peer=PeerUser(int(DB_CHANNEL_ID))
            )
            await processing.delete()
            return

        song = Song(f"https://open.spotify.com/track/{song_id}")
        await processing.edit(DOWNLOADING)
        yt_link = song.yt_link()
        if yt_link is None:
            print(f'[YOUTUBE] song not found: {song.uri}')
            await processing.delete()
            await event.respond(f"{song.track_name}\n{SONG_NOT_FOUND}")
            return
        file_path = song.download(yt_link=yt_link)
        await processing.edit(UPLOADING)

        upload_file = await CLIENT.upload_file(file_path)
        template = await song.song_telethon_template()  # Await the coroutine
        new_message = await CLIENT.send_file(
            DB_CHANNEL_ID,
            file=upload_file,
            caption=template[0],  # Use the first element of the tuple
            supports_streaming=True,
            attributes=(
                types.DocumentAttributeAudio(
                    title=song.track_name,
                    duration=song.duration_to_seconds,
                    performer=song.artist_name
                ),
            ),
            progress_callback=lambda sent, total: Song.progress_callback(processing, sent, total)
        )
        song.save_db(event.sender_id, new_message.id)
        message_id = new_message.id

        # Forward with template message and buttons
        forwarded_message = await CLIENT.forward_messages(
            entity=event.chat_id,
            messages=message_id,
            from_peer=PeerUser(int(DB_CHANNEL_ID))
        )
        await forwarded_message.reply(
            template[0],  # Message
            file=await CLIENT.upload_file(await song.download_song_cover()),  # Cover image
            buttons=template[2]  # Buttons
        )
        await processing.delete()

    @staticmethod
    async def upload_album_on_telegram(event: events.CallbackQuery.Event, album_id):
        from spotify.album import Album
        album = Album(album_id)
        processing = await event.respond(PROCESSING)

        # Get cover photo and name from the first track
        if album.track_list:
            first_track_id = album.track_list[0]
            first_song = Song(f"https://open.spotify.com/track/{first_track_id}")
            album_cover_url = first_song.album_cover
            album_name = first_song.album_name  # Use album name from first track
            response = requests.get(album_cover_url)
            cover_file = f'covers/album_{album_id}.png'
            with open(cover_file, 'wb') as f:
                f.write(response.content)
            cover = await CLIENT.upload_file(cover_file)
        else:
            cover = None
            album_name = "Unknown Album"

        # Send album summary with buttons (no file in initial message)
        album_message = f'''
💿 Album: `{album_name}`
📝 Tracks: `{len(album.track_list)}`
📅 Release Date: `{first_song.release_date if album.track_list else "N/A"}`
[IMAGE]({album_cover_url or ""})
        '''
        buttons = []  # No buttons as per request to avoid errors
        sent_message = await event.respond(album_message, buttons=buttons)
        if cover:
            await sent_message.reply(file=cover)

        # Download and upload tracks automatically
        for index, track_id in enumerate(album.track_list):
            song = Song(f"https://open.spotify.com/track/{track_id}")
            await processing.edit(f"Downloading track {index + 1}/{len(album.track_list)}")
            yt_link = song.yt_link()
            if yt_link is None:
                print(f'[YOUTUBE] song not found: {song.uri}')
                continue
            file_path = song.download(yt_link=yt_link)
            await processing.edit(f"Uploading track {index + 1}/{len(album.track_list)}")

            upload_file = await CLIENT.upload_file(file_path)
            template = await song.song_telethon_template()  # Await the coroutine
            new_message = await CLIENT.send_file(
                DB_CHANNEL_ID,
                file=upload_file,
                caption=template[0],  # Use the first element of the tuple
                supports_streaming=True,
                attributes=(
                    types.DocumentAttributeAudio(
                        release_date=song.release_date,
                        title=song.track_name,
                        duration=song.duration_to_seconds,
                        performer=song.artist_name
                    ),
                ),
                progress_callback=lambda sent, total: Song.progress_callback(processing, sent, total)
            )
            song.save_db(event.sender_id, new_message.id)
            message_id = new_message.id

            # Forward the track to the user
            await CLIENT.forward_messages(
                entity=event.chat_id,
                messages=message_id,
                from_peer=PeerUser(int(DB_CHANNEL_ID))
            )

        await processing.delete()

    @staticmethod
    async def upload_playlist_on_telegram(event: events.CallbackQuery.Event, playlist_id):
        from spotify.playlist import Playlist
        playlist = Playlist(playlist_id)
        tracks = playlist.get_playlist_tracks(playlist_id)
        processing = await event.respond(PROCESSING)

        # Get cover photo and name from the first track
        if tracks:
            first_track_id = tracks[0]['track']['id']
            first_song = Song(f"https://open.spotify.com/track/{first_track_id}")
            playlist_cover_url = first_song.album_cover
            playlist_name = tracks[0]['track']['album']['name']  # Use album name from first track as proxy
            response = requests.get(playlist_cover_url)
            cover_file = f'covers/playlist_{playlist_id}.png'
            with open(cover_file, 'wb') as f:
                f.write(response.content)
            cover = await CLIENT.upload_file(cover_file)
        else:
            cover = None
            playlist_name = "Unknown Playlist"

        # Send playlist summary with buttons (no file in initial message)
        playlist_message = f'''
🎧 Playlist: `{playlist_name}`
📝 Tracks: `{len(tracks)}`
📅 Release Date: `{first_song.release_date if tracks else "N/A"}`  # Use release date from first track as proxy
[IMAGE]({playlist_cover_url or ""})
        '''
        buttons = []  # No buttons as per request to avoid errors
        sent_message = await event.respond(playlist_message, buttons=buttons)
        if cover:
            await sent_message.reply(file=cover)

        # Download and upload tracks automatically
        for index, item in enumerate(tracks):
            track_id = item['track']['id']
            song = Song(f"https://open.spotify.com/track/{track_id}")
            await processing.edit(f"Downloading track {index + 1}/{len(tracks)}")
            yt_link = song.yt_link()
            if yt_link is None:
                print(f'[YOUTUBE] song not found: {song.uri}')
                continue
            file_path = song.download(yt_link=yt_link)
            await processing.edit(f"Uploading track {index + 1}/{len(tracks)}")

            upload_file = await CLIENT.upload_file(file_path)
            template = await song.song_telethon_template()  # Await the coroutine
            new_message = await CLIENT.send_file(
                DB_CHANNEL_ID,
                file=upload_file,
                caption=template[0],  # Use the first element of the tuple
                supports_streaming=True,
                attributes=(
                    types.DocumentAttributeAudio(
                        release_date=song.release_date,
                        title=song.track_name,
                        duration=song.duration_to_seconds,
                        performer=song.artist_name
                    ),
                ),
                progress_callback=lambda sent, total: Song.progress_callback(processing, sent, total)
            )
            song.save_db(event.sender_id, new_message.id)
            message_id = new_message.id

            # Forward the track to the user
            await CLIENT.forward_messages(
                entity=event.chat_id,
                messages=message_id,
                from_peer=PeerUser(int(DB_CHANNEL_ID))
            )

        await processing.delete()
