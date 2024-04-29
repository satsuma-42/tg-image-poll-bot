import logging
import os
from telegram import (
    Update,
    InlineQueryResultArticle,
    InputTextMessageContent,
    ReplyKeyboardRemove,
)
from telegram.constants import ParseMode
from telegram.ext import (
    filters,
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    InlineQueryHandler,
    MessageHandler,
    PollAnswerHandler,
    ConversationHandler,
)

TOKEN = os.environ["TOKEN"]
CHAT_ID = int(os.environ["CHAT_ID"])

logging.basicConfig(
    level=logging.ERROR, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

QUESTION, PHOTO, OPTION_ONE, OPTION_TWO = range(4)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text="I'm a bot, please talk to me!"
    )

async def id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text=update.effective_chat.id
    )

async def poll(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "What is the question for this poll?",
        reply_markup=ReplyKeyboardRemove(),
    )

    return QUESTION


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
    question = context.chat_data["question"]

    context.chat_data["options"].append(update.message.text)
    options = context.chat_data["options"]

    await context.bot.send_photo(chat_id=CHAT_ID, photo="user_photo.jpg")

    message = await context.bot.send_poll(
        CHAT_ID,
        question,
        options,
        is_anonymous=True,
        allows_multiple_answers=True,
    )
    # Save some info about the poll the bot_data for later use in receive_poll_answer
    payload = {
        message.poll.id: {
            "questions": options,
            "message_id": message.message_id,
            "chat_id": CHAT_ID,
            "answers": 0,
        }
    }
    context.bot_data.update(payload)
    
    return ConversationHandler.END


async def receive_poll_answer(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Summarize a users poll vote"""
    answer = update.poll_answer
    answered_poll = context.bot_data[answer.poll_id]
    try:
        questions = answered_poll["questions"]
    # this means this poll answer update is from an old poll, we can't do our answering then
    except KeyError:
        return
    selected_options = answer.option_ids
    answer_string = ""
    for question_id in selected_options:
        if question_id != selected_options[-1]:
            answer_string += questions[question_id] + " and "
        else:
            answer_string += questions[question_id]
    await context.bot.send_message(
        answered_poll["chat_id"],
        f"{update.effective_user.mention_html()} feels {answer_string}!",
        parse_mode=ParseMode.HTML,
    )
    answered_poll["answers"] += 1


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


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display a help message"""
    await update.message.reply_text("Use /quiz, /poll or /preview to test this bot.")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the conversation."""
    user = update.message.from_user
    await update.message.reply_text(
        "Bye! I hope we can talk again some day.", reply_markup=ReplyKeyboardRemove()
    )

    return ConversationHandler.END


if __name__ == "__main__":
    application = ApplicationBuilder().token(TOKEN).build()

    start_handler = CommandHandler("start", start)
    application.add_handler(start_handler)
    
    id_handler = MessageHandler(filters.COMMAND & filters.Text("/id"), id)
    application.add_handler(id_handler)

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("poll", poll)],
        states={
            QUESTION: [MessageHandler(filters.TEXT, question)],
            PHOTO: [MessageHandler(filters.PHOTO, photo)],
            OPTION_ONE: [MessageHandler(filters.TEXT, option_one)],
            OPTION_TWO: [MessageHandler(filters.TEXT, option_two)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)

    application.add_handler(MessageHandler(filters.POLL, receive_poll))
    application.add_handler(PollAnswerHandler(receive_poll_answer))

    application.run_polling()
