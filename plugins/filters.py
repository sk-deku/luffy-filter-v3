import io
import logging
from pyrogram import filters, Client, enums
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from database.filters_mdb import add_filter, get_filters, delete_filter, count_filters
from database.connections_mdb import active_connection
from utils import get_file_id, parser, split_quotes
from info import ADMINS
from database.users_chats_db import db
from database.users_chats_db import Database
from info import DATABASE_URI, DATABASE_NAME

# Logger setup
logger = logging.getLogger(__name__)

db = Database(DATABASE_URI, DATABASE_NAME)

@Client.on_message(filters.command(['filter', 'add']) & filters.incoming)
async def addfilter(client, message):
    """Handles adding new filters to the database."""
    userid = message.from_user.id if message.from_user else None
    if not userid:
        return await message.reply("You are an anonymous admin. Use /connect in PM.")

    chat_type = message.chat.type
    args = message.text.split(None, 1)

    if chat_type == enums.ChatType.PRIVATE:
        grpid = await active_connection(str(userid))
        if not grpid:
            return await message.reply("You're not connected to any groups!")

        grp_id = grpid
        try:
            chat = await client.get_chat(grpid)
            title = chat.title
        except:
            return await message.reply("Make sure I'm present in your group!")

    elif chat_type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        grp_id = message.chat.id
        title = message.chat.title
    else:
        return

    st = await client.get_chat_member(grp_id, userid)
    if (
        st.status not in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]
        and str(userid) not in ADMINS
    ):
        return

    if len(args) < 2:
        return await message.reply("Command Incomplete!")

    extracted = split_quotes(args[1])
    text = extracted[0].lower()

    if not message.reply_to_message and len(extracted) < 2:
        return await message.reply("Add some content to save your filter!")

    fileid, reply_text, btn, alert = None, "", [], None

    if message.reply_to_message:
        msg = get_file_id(message.reply_to_message)
        fileid = msg.file_id if msg else None

        if message.reply_to_message.text:
            reply_text, btn, alert = parser(message.reply_to_message.text.html, text)
        elif message.reply_to_message.caption:
            reply_text, btn, alert = parser(message.reply_to_message.caption.html, text)

    elif len(extracted) >= 2:
        reply_text, btn, alert = parser(extracted[1], text)

    if not reply_text and not btn:
        return await message.reply("You must add either text or buttons!")

    await add_filter(grp_id, text, reply_text, btn, fileid, alert)

    await message.reply_text(
        f"✅ Filter for `{text}` added in **{title}**",
        quote=True,
        parse_mode=enums.ParseMode.MARKDOWN
    )


@Client.on_message(filters.command(['viewfilters', 'filters']) & filters.incoming)
async def get_all(client, message):
    """Handles listing all filters in a group."""
    userid = message.from_user.id if message.from_user else None
    if not userid:
        return await message.reply("You are an anonymous admin. Use /connect in PM.")

    chat_type = message.chat.type

    if chat_type == enums.ChatType.PRIVATE:
        grpid = await active_connection(str(userid))
        if not grpid:
            return await message.reply("You're not connected to any groups!")

        grp_id = grpid
        title = (await client.get_chat(grpid)).title

    elif chat_type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        grp_id = message.chat.id
        title = message.chat.title
    else:
        return

    st = await client.get_chat_member(grp_id, userid)
    if (
        st.status not in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]
        and str(userid) not in ADMINS
    ):
        return

    texts = await get_filters(grp_id)
    count = await count_filters(grp_id)

    if not count:
        return await message.reply(f"No active filters in **{title}**")

    filter_list = f"Total filters in **{title}**: {count}\n\n" + "\n".join([f" ×  `{text}`" for text in texts])

    if len(filter_list) > 4096:
        with io.BytesIO(filter_list.encode()) as keyword_file:
            keyword_file.name = "filters.txt"
            return await message.reply_document(keyword_file, quote=True)

    await message.reply(filter_list, quote=True, parse_mode=enums.ParseMode.MARKDOWN)


@Client.on_message(filters.command('del') & filters.incoming)
async def deletefilter(client, message):
    """Handles deleting a specific filter."""
    userid = message.from_user.id if message.from_user else None
    if not userid:
        return await message.reply("You are an anonymous admin. Use /connect in PM.")

    chat_type = message.chat.type

    if chat_type == enums.ChatType.PRIVATE:
        grpid = await active_connection(str(userid))
        if not grpid:
            return await message.reply("You're not connected to any groups!")

        grp_id = grpid

    elif chat_type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        grp_id = message.chat.id
    else:
        return

    st = await client.get_chat_member(grp_id, userid)
    if (
        st.status not in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]
        and str(userid) not in ADMINS
    ):
        return

    try:
        cmd, text = message.text.split(" ", 1)
    except:
        return await message.reply(
            "❌ Mention the filter name you want to delete!\n\n"
            "Usage: `/del filtername`\n"
            "Use `/viewfilters` to see all available filters.",
            quote=True
        )

    query = text.lower()
    await delete_filter(message, query, grp_id)


@Client.on_message(filters.text & filters.group)
async def auto_filter(client, message):
    """Handles filtering messages automatically."""
    user_id = message.from_user.id

    # Check if user has enough tokens
    user_tokens = await db.get_tokens(user_id)
    if user_tokens <= 0:
        return await message.reply("❌ You don't have enough tokens! Use /verify in PM to earn more.")

    results = await get_filters(message.chat.id)
    if not results:
        return

    buttons = [
        [InlineKeyboardButton(file["file_name"], callback_data=f"file_{file['_id']}")]
        for file in results
    ]

    await message.reply("🔍 Select a file:", reply_markup=InlineKeyboardMarkup(buttons))


@Client.on_callback_query(filters.regex(r"^file_(.*)"))
async def send_file(client, callback_query):
    """Handles sending files when a user selects one."""
    user_id = callback_query.from_user.id

    # Check token balance
    user_tokens = await db.get_tokens(user_id)
    if user_tokens <= 0:
        return await callback_query.answer("❌ Not enough tokens! Use /verify in PM to earn more.", show_alert=True)

    file_id = callback_query.data.split("_")[1]
    file_data = await db.get_file_by_id(file_id)  # Correct function call

    if not file_data:
        return await callback_query.answer("❌ File not found!", show_alert=True)

    # Deduct 1 token
    await db.update_tokens(user_id, -1)

    # Send file in PM
    try:
        await client.send_document(user_id, file_data["file_id"], caption="Here's your file! 📂")
        await callback_query.answer("✅ File sent in PM!", show_alert=True)
    except Exception as e:
        logger.error(f"Error sending file: {e}")
        await callback_query.answer("❌ Failed to send file!", show_alert=True)
