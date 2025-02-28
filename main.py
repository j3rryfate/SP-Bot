from telegram import BOT_TOKEN, CLIENT
from telethon import events
from models import session, Subscription, User
from decouple import config
import datetime
import pytz
from sqlalchemy.exc import SQLAlchemyError
import re  # Added for URL parsing

ADMIN_ID = int(config('ADMIN_ID'))

async def check_subscription(user_id):
    try:
        user = session.query(User).filter_by(telegram_id=user_id).first()
        if not user:
            return False
        if user.is_banned:
            return False
        sub = session.query(Subscription).filter_by(user_id=user.id, approved=1).first()
        if not sub:
            return False
        utc = pytz.UTC
        end_date = utc.localize(sub.end_date) if sub.end_date else datetime.datetime.min.replace(tzinfo=utc)
        if end_date < datetime.datetime.now(datetime.UTC):
            return False
        return True
    except SQLAlchemyError as e:
        session.rollback()
        print(f"Database error in check_subscription: {e}")
        return False

@CLIENT.on(events.NewMessage(pattern='/start'))
async def start(event):
    user_id = event.sender_id
    if await check_subscription(user_id):
        await event.respond("Welcome back! Your subscription is active. Use /search <song_name> or send a Spotify link to download.")
    else:
        await event.respond("Welcome! Use /subscribe to get access or /search <song_name> to try without subscription.")

@CLIENT.on(events.NewMessage(pattern=r'/search (.+)'))
async def search(event):
    query = event.pattern_match.group(1)
    from spotify import search_single  # Assuming spotify.py in root
    songs = search_single(query)
    if songs:
        message = "Search Results:\n"
        buttons = []
        for i, song in enumerate(songs[:5]):  # Limit to 5 songs
            buttons.append([Button.inline(f"{song.track_name} - {song.artist_name}", data=f"song:{song.id}")])
        await event.respond(message, buttons=buttons)
    else:
        await event.respond("No songs found.")

@CLIENT.on(events.NewMessage(pattern=r'https?://open\.spotify\.com/track/([a-zA-Z0-9]+)\??.*'))
async def handle_spotify_link(event):
    user_id = event.sender_id
    if not await check_subscription(user_id):
        await event.respond("သင့်မှာ active subscription မရှိပါ။ /subscribe ကို သုံးပါ။")
        return
    song_id = event.pattern_match.group(1)
    print(f'[TELEGRAM] Handling Spotify link for song_id: {song_id}')
    from spotify.song import Song
    await Song.upload_on_telegram(event, song_id)

@CLIENT.on(events.NewMessage(pattern='/subscribe'))
async def subscribe(event):
    user_id = event.sender_id
    try:
        user = session.query(User).filter_by(telegram_id=user_id).first()
        if not user:
            user = User(telegram_id=user_id)
            session.add(user)
            session.commit()
        if user.is_banned:
            await event.respond("You are banned from using this bot.")
            return
        sub = session.query(Subscription).filter_by(user_id=user.id, approved=0).first()
        if not sub:
            sub = Subscription(user_id=user.id)
            session.add(sub)
            session.commit()
        await event.respond("Please send a payment screenshot to the admin for verification.")
    except SQLAlchemyError as e:
        session.rollback()
        print(f"Database error in subscribe: {e}")
        await event.respond("Something went wrong. Please try again later.")

@CLIENT.on(events.NewMessage(func=lambda e: e.photo and e.is_private))
async def handle_payment_screenshot(event):
    user_id = event.sender_id
    try:
        await CLIENT.forward_messages(ADMIN_ID, event.message)
        await CLIENT.send_message(ADMIN_ID, f"Payment screenshot from User ID: {user_id}")
        await event.respond("Payment screenshot forwarded to admin. Please wait for approval.")
    except Exception as e:
        print(f"Error in handle_payment_screenshot: {e}")
        await event.respond("Failed to forward screenshot. Please try again.")

@CLIENT.on(events.NewMessage(pattern=r'/approve_sub (\d+) (\d+)'))
async def approve_subscription(event):
    if event.sender_id != ADMIN_ID:
        await event.respond("You are not authorized to use this command.")
        return
    user_telegram_id, days = map(int, event.raw_text.split()[1:])
    try:
        user = session.query(User).filter_by(telegram_id=user_telegram_id).first()
        if not user:
            await event.respond("User not found.")
            return
        sub = session.query(Subscription).filter_by(user_id=user.id, approved=0).first()
        if not sub:
            sub = Subscription(user_id=user.id)
        sub.start_date = datetime.datetime.now(datetime.UTC)
        sub.end_date = sub.start_date + datetime.timedelta(days=days)
        sub.approved = 1
        session.commit()
        expiry_date = sub.end_date.strftime("%Y-%m-%d")
        await event.respond(f"Subscription approved for user {user_telegram_id} for {days} days.")
        await CLIENT.send_message(
            user_telegram_id, 
            f"Your subscription has been approved! You can use the bot until {expiry_date}."
        )
    except SQLAlchemyError as e:
        session.rollback()
        print(f"Database error in approve_subscription: {e}")
        await event.respond("Failed to approve subscription. Please try again.")

@CLIENT.on(events.NewMessage(pattern=r'/ban (\d+)'))
async def ban_user(event):
    if event.sender_id != ADMIN_ID:
        await event.respond("You are not authorized to use this command.")
        return
    user_telegram_id = int(event.raw_text.split()[1])
    try:
        user = session.query(User).filter_by(telegram_id=user_telegram_id).first()
        if not user:
            await event.respond("User not found.")
            return
        user.is_banned = True
        session.commit()
        await event.respond(f"User {user_telegram_id} has been banned.")
        await CLIENT.send_message(user_telegram_id, "You have been banned from using this bot.")
    except SQLAlchemyError as e:
        session.rollback()
        print(f"Database error in ban_user: {e}")
        await event.respond("Failed to ban user. Please try again.")

@CLIENT.on(events.NewMessage(pattern=r'/unban (\d+)'))
async def unban_user(event):
    if event.sender_id != ADMIN_ID:
        await event.respond("You are not authorized to use this command.")
        return
    user_telegram_id = int(event.raw_text.split()[1])
    try:
        user = session.query(User).filter_by(telegram_id=user_telegram_id).first()
        if not user:
            await event.respond("User not found.")
            return
        if not user.is_banned:
            await event.respond(f"User {user_telegram_id} is not banned.")
            return
        user.is_banned = False
        session.commit()
        await event.respond(f"User {user_telegram_id} has been unbanned.")
        await CLIENT.send_message(user_telegram_id, "You have been unbanned and can now use the bot again.")
    except SQLAlchemyError as e:
        session.rollback()
        print(f"Database error in unban_user: {e}")
        await event.respond("Failed to unban user. Please try again.")

@CLIENT.on(events.NewMessage(pattern='/status'))
async def check_status(event):
    user_id = event.sender_id
    try:
        user = session.query(User).filter_by(telegram_id=user_id).first()
        if not user:
            await event.respond("You are not registered yet. Use /subscribe to start.")
            return
        if user.is_banned:
            await event.respond("You are banned from using this bot.")
            return
        sub = session.query(Subscription).filter_by(user_id=user.id, approved=1).first()
        if not sub:
            await event.respond("You don't have an active subscription. Use /subscribe to get access.")
            return
        utc = pytz.UTC
        end_date = utc.localize(sub.end_date) if sub.end_date else datetime.datetime.min.replace(tzinfo=utc)
        if end_date < datetime.datetime.now(datetime.UTC):
            await event.respond("You don't have an active subscription. Use /subscribe to get access.")
            return
        expiry_date = sub.end_date.strftime("%Y-%m-%d")
        await event.respond(f"Your subscription is active until {expiry_date}.")
    except SQLAlchemyError as e:
        session.rollback()
        print(f"Database error in check_status: {e}")
        await event.respond("Something went wrong while checking your status. Please try again later.")

@CLIENT.on(events.CallbackQuery(pattern=r'download_song:.*'))
async def handle_download(event: events.CallbackQuery.Event):
    if not await check_subscription(event.sender_id):
        await event.respond("သင့်မှာ active subscription မရှိပါ။ /subscribe ကို သုံးပါ။")
        return
    data = event.data.decode('utf-8')
    song_id = data[14:]  # Extract song_id after "download_song:"
    print(f'[TELEGRAM] Download song callback query: {song_id}')
    await Song.upload_on_telegram(event, song_id)

if __name__ == '__main__':
    print('[BOT] Starting...')
    CLIENT.start(bot_token=BOT_TOKEN)
    CLIENT.run_until_disconnected()
