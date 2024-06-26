import logging
import os
import random
from telegram import (
    Update,
    ReplyKeyboardRemove,
)
from telegram.constants import ParseMode
from telegram.ext import (
    filters,
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    PollAnswerHandler,
    ConversationHandler,
)

TOKEN = os.environ["TOKEN"]
ORIGIN_CHAT_ID = int(os.environ["ORIGIN_CHAT_ID"])
DEST_CHAT_ID = int(os.environ["DEST_CHAT_ID"])


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    filename="./data/log.log",
    filemode="a",
)
# set higher logging level for httpx to avoid all GET and POST requests being logged
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

QUESTION, PHOTO, OPTION_ONE, OPTION_TWO, DESCRIPTION, DURATION = range(6)

# /start


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Hello, world! Enter /newpoll to start creating a poll.",
    )


# /help


async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="/id - Output the current chat's ID\n"
        "/newpoll - Start creating a new poll\n"
        "/cancel - Can be used during the /newpoll conversation to cancel poll creation",
    )


# /id


async def id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=update.effective_chat.id
    )


# /newpoll conversation


async def newpoll(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_chat.id == ORIGIN_CHAT_ID:
        await update.message.reply_text(
            "What is the question for this poll?",
            reply_markup=ReplyKeyboardRemove(),
        )

        return QUESTION
    else:
        await update.message.reply_text(
            "You do not have permission to use this command",
            reply_markup=ReplyKeyboardRemove(),
        )

        return ConversationHandler.END


async def question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.chat_data["question"] = update.message.text

    await update.message.reply_text(
        "Please share the image to use for this poll",
        reply_markup=ReplyKeyboardRemove(),
    )

    return PHOTO


async def photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_file = await update.message.photo[-1].get_file()
    await photo_file.download_to_drive("user_photo.jpg")

    await update.message.reply_text(
        "Option one:",
        reply_markup=ReplyKeyboardRemove(),
    )

    return OPTION_ONE


async def option_one(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.chat_data["options"] = []
    context.chat_data["options"].append(update.message.text)

    await update.message.reply_text(
        "Option two:",
        reply_markup=ReplyKeyboardRemove(),
    )

    return OPTION_TWO


async def option_two(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.chat_data["options"].append(update.message.text)

    await update.message.reply_text(
        "Description (Type /skip to skip):",
        reply_markup=ReplyKeyboardRemove(),
    )

    return DESCRIPTION


async def description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.chat_data["description"] = update.message.text

    await update.message.reply_text(
        "Duration (In hours):",
        reply_markup=ReplyKeyboardRemove(),
    )

    return DURATION


async def skip_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Duration (In hours):",
        reply_markup=ReplyKeyboardRemove(),
    )

    return DURATION


async def duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.chat_data["duration"] = float(update.message.text) * 3600

    question = context.chat_data["question"]
    options = context.chat_data["options"]

    duration = context.chat_data["duration"]

    await context.bot.send_photo(chat_id=DEST_CHAT_ID, photo="user_photo.jpg")

    message = await context.bot.send_poll(
        DEST_CHAT_ID,
        question,
        options,
        is_anonymous=False,
        allows_multiple_answers=False,
    )

    if "description" in context.chat_data:
        description = context.chat_data["description"]
        await context.bot.send_message(
            chat_id=DEST_CHAT_ID,
            reply_to_message_id=message.message_id,
            text=description,
        )

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"The poll has been shared, and should conclude in {update.message.text} hours",
    )

    # Save some info about the poll the bot_data for later use in receive_poll_answer
    payload = {
        message.poll.id: {
            "questions": options,
            "message_id": message.message_id,
            "chat_id": DEST_CHAT_ID,
            "answers": 0,
            "voters": [[], []],
        }
    }
    context.bot_data.update(payload)

    context.job_queue.run_once(
        callback_end_poll, duration, data=message.message_id, chat_id=DEST_CHAT_ID
    )

    return ConversationHandler.END


# End /newpoll conversation

# Poll update handling


async def receive_poll_answer(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    answer = update.poll_answer
    answered_poll = context.bot_data[answer.poll_id]
    username = update.effective_user.username
    first_name = update.effective_user.first_name

    answered_poll["voters"][int(answer.option_ids[0])].append(
        {"username": username, "first_name": first_name}
    )


async def receive_poll(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """On receiving polls, reply to it by a closed poll copying the received poll"""
    actual_poll = update.effective_message.poll
    # Only need to set the question and options, since all other parameters don't matter for
    # a closed poll
    await update.effective_message.reply_poll(
        question=actual_poll.question,
        options=[o.text for o in actual_poll.options],
        # with is_closed true, the poll/quiz is immediately closed
        is_closed=True,
        reply_markup=ReplyKeyboardRemove(),
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the conversation."""
    user = update.message.from_user
    await update.message.reply_text("Bye!", reply_markup=ReplyKeyboardRemove())

    return ConversationHandler.END


# Job queue stuff


async def callback_end_poll(context: ContextTypes.DEFAULT_TYPE):
    message_id = context.job.data

    closed_poll = await context.bot.stop_poll(DEST_CHAT_ID, int(message_id))
    poll_data = context.bot_data[closed_poll.id]
    logger.info("Poll data for %s: %s", closed_poll.question, poll_data)

    data = closed_poll.options

    # Picking which option has the highest voter_count, and checking if a draw

    max_voter_count = float("-inf")  # Initialize with negative infinity
    max_index = None

    for index, item in enumerate(data):
        voter_count = item["voter_count"]
        if voter_count > max_voter_count:
            max_voter_count = voter_count
            max_index = index
            text = data[max_index].text
            winning_voters = poll_data["voters"][max_index]
        elif voter_count == max_voter_count:
            text = "⚔ Looks like this one was a draw! ⚔"
            winning_voters = (
                poll_data["voters"][0] + poll_data["voters"][1]
            )  # If a draw, 'Winning voter' and 'Random voter' will be picked from both

    # await context.bot.send_message(
    #     chat_id=DEST_CHAT_ID, reply_to_message_id=message_id, text=text
    # )

    random_winning_voter = random.choice(winning_voters)

    all_voters = poll_data["voters"][0] + poll_data["voters"][1]
    random_voter = random_winning_voter  # Hack to avoid issues from only one voter, and to run while loop
    if len(all_voters) > 1:
        while random_voter == random_winning_voter:  # Make sure a different random voter is chosen
            random_voter = random.choice(all_voters)

    await context.bot.send_message(
        chat_id=DEST_CHAT_ID,
        reply_to_message_id=message_id,
        parse_mode="Markdown",
        text="~~~\n"
        "👑👑👑👑👑\n"
        f'Here are the _"{closed_poll.question}"_  DuelPoll winners!\n'
        "👑👑👑👑👑\n\n"
        "🏆 Poll Winner 🏆 \n"
        f"*{text}*" + "\n\n"
        "🥇 Winning Voter Prize 🥇\n"
        f'Username: *{random_winning_voter["username"]}*' + "\n"
        f'Name: *{random_winning_voter["first_name"]}*' + "\n"
        "~~~",
    )

    # "🌟 Random Voter Prize 🌟\n"  # dizzy symbol
    #     f'Username: *{random_voter["username"]}*' + "\n"
    #     f'Name: *{random_voter["first_name"]}*' + "\n"

if __name__ == "__main__":
    application = ApplicationBuilder().token(TOKEN).build()
    job_queue = application.job_queue

    # /start
    start_handler = CommandHandler("start", start)
    application.add_handler(start_handler)

    # /help
    help_handler = CommandHandler("help", help)
    application.add_handler(help_handler)

    # /newpoll
    id_handler = MessageHandler(filters.COMMAND & filters.Text("/id"), id)
    application.add_handler(id_handler)

    # /newpoll
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("newpoll", newpoll)],
        states={
            QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, question)],
            PHOTO: [MessageHandler(filters.PHOTO, photo)],
            OPTION_ONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, option_one)],
            OPTION_TWO: [MessageHandler(filters.TEXT & ~filters.COMMAND, option_two)],
            DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, description),
                CommandHandler("skip", skip_description),
            ],
            DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, duration)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.POLL, receive_poll))
    application.add_handler(PollAnswerHandler(receive_poll_answer))

    application.run_polling()
