import telebot
import threading
import time
import smtplib
import logging
import os
import hashlib
import asyncio
import random
from telebot import types
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, ConversationHandler, Filters
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, FloodWaitError
from telethon.tl.functions.account import ReportPeerRequest
from telethon.tl.types import (
    InputReportReasonSpam, InputReportReasonViolence, InputReportReasonPornography,
    InputReportReasonChildAbuse, InputReportReasonCopyright, InputReportReasonDrugs,
    InputReportReasonOther, InputReportReasonFake, PeerUser
)
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
import re
import traceback

# إعدادات تسجيل الأخطاء
logging.basicConfig(filename='bot_errors.log', level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# الثوابت
API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7473183889:AAGrt-PrHpbY2g6mT50KM1DvrWykcgpp-iQ")
DEVELOPER_ID = int(os.getenv("DEVELOPER_ID", 7532752552))
TELETHON_API_ID = 25612365  # استبدل بـ API ID الخاص بك
TELETHON_API_HASH = '983959cac2c32428b55d7c929a146b80'  # استبدل بـ API Hash الخاص بك

# متغيرات عامة
bot = telebot.TeleBot(API_TOKEN)
authorized_users = []
banned_users = []
vip_users = []
user_points = {}
all_users = set()
user_email_accounts = {}
report_channel_or_group_id = {}
report_subject = {}
report_message = {}
report_image = {}
message_count = {}
send_interval = {}
sending_in_progress = {}
stop_sending = {}
send_schedule = {}
templates = {}
bot_enabled = True
DECORATION = "⫷✧ {} ✧⫸"

# معطيات الشد الداخلي
internal_report_data = {}
(ACCOUNT, CODE, GROUP, MESSAGES, REPORT_TYPE, REPORT_MESSAGE, REPORT_COUNT, START_REPORT, STOP_REPORT, INFO, PASSWORD, PROTECTION) = range(12)

# دوال مساعدة
def is_developer(user_id):
    return user_id == DEVELOPER_ID

def is_authorized(user_id):
    return user_id in authorized_users and user_id not in banned_users

def is_vip(user_id):
    return user_id in vip_users

def validate_email(email):
    return re.match(r"[^@]+@[^@]+\.[^@]+", email) is not None

def encrypt_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def log_error(user_id, error, details=""):
    error_message = f"خطأ عند المستخدم {user_id}: {str(error)}\nالتفاصيل: {details}\nTraceback: {traceback.format_exc()}"
    logger.error(error_message)
    try:
        bot.send_message(DEVELOPER_ID, DECORATION.format(f"تنبيه خطأ\n{error_message}"))
    except Exception as e:
        logger.error(f"فشل في إرسال تنبيه للمطور: {str(e)}")

def send_notification(user_id, text):
    try:
        bot.send_message(user_id, DECORATION.format(text))
    except Exception as e:
        log_error(user_id, e, "فشل في إرسال إشعار")

def send_email(email, password, subject, message, to_email, image=None):
    try:
        msg = MIMEMultipart()
        msg['From'] = email
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(message, 'plain'))
        if image:
            img = MIMEImage(image)
            msg.attach(img)

        if "gmail.com" in email:
            server = smtplib.SMTP("smtp.gmail.com", 587)
        elif "yahoo.com" in email:
            server = smtplib.SMTP("smtp.mail.yahoo.com", 587)
        elif "outlook.com" in email or "hotmail.com" in email:
            server = smtplib.SMTP("smtp-mail.outlook.com", 587)
        else:
            raise ValueError("خدمة الإيميل غير مدعومة")

        server.starttls()
        server.login(email, password)
        server.sendmail(email, to_email, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        log_error(to_email, e, f"فشل في إرسال إيميل من {email} إلى {to_email}")
        return False

# قسم الشد الداخلي
def internal_start(update: Update, context):
    user_id = update.message.chat_id
    if user_id not in internal_report_data:
        internal_report_data[user_id] = {
            'protection_enabled': False,
            'delay_between_reports': 5,
            'stop_report': False
        }
    keyboard = [
        [InlineKeyboardButton("إضافة حساب تيليجرام", callback_data='internal_add_account'),
         InlineKeyboardButton("إضافة مجموعة/قناة", callback_data='internal_add_group')],
        [InlineKeyboardButton("تعيين الرسائل", callback_data='internal_set_messages'),
         InlineKeyboardButton("عرض الحسابات", callback_data='internal_view_accounts')],
        [InlineKeyboardButton("تعيين نوع الإبلاغ", callback_data='internal_set_report_type'),
         InlineKeyboardButton("تعيين رسالة الإبلاغ", callback_data='internal_set_report_message')],
        [InlineKeyboardButton("تعيين عدد الإبلاغات", callback_data='internal_set_report_count'),
         InlineKeyboardButton("حماية الحسابات", callback_data='internal_toggle_protection')],
        [InlineKeyboardButton("بدء الإبلاغ", callback_data='internal_start_report'),
         InlineKeyboardButton("إيقاف الإبلاغ", callback_data='internal_stop_report')],
        [InlineKeyboardButton("عرض المعلومات", callback_data='internal_view_info')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    context.bot.send_message(user_id, 'قسم الشد الداخلي (VIP فقط):', reply_markup=reply_markup)
    return ConversationHandler.END

def internal_button(update: Update, context):
    query = update.callback_query
    query.answer()
    user_id = query.message.chat_id
    action_mapping = {
        'internal_add_account': (ACCOUNT, "يرجى إدخال رقم الحساب:"),
        'internal_add_group': (GROUP, "يرجى إدخال رابط المجموعة/القناة:"),
        'internal_set_messages': (MESSAGES, "يرجى إدخال روابط الرسائل (رابط واحد في كل سطر):"),
        'internal_set_report_type': (REPORT_TYPE, "اختر نوع الإبلاغ:"),
        'internal_set_report_message': (REPORT_MESSAGE, "يرجى إدخال رسالة الإبلاغ:"),
        'internal_set_report_count': (REPORT_COUNT, "يرجى إدخال عدد الإبلاغات:"),
        'internal_start_report': (START_REPORT, "جاري بدء الإبلاغ..."),
        'internal_stop_report': (STOP_REPORT, "جاري إيقاف الإبلاغ..."),
        'internal_view_info': (INFO, "عرض المعلومات"),
        'internal_toggle_protection': (PROTECTION, "إعدادات حماية الحسابات:")
    }
    if query.data in action_mapping:
        state, message = action_mapping[query.data]
        context.bot.send_message(user_id, text=message)
        return state
    if query.data == 'internal_view_accounts':
        accounts = internal_report_data.get(user_id, {}).get('accounts', [])
        keyboard = [[InlineKeyboardButton(account, callback_data=f'internal_account_{account}')] for account in accounts]
        reply_markup = InlineKeyboardMarkup(keyboard)
        context.bot.send_message(user_id, text="الحسابات:", reply_markup=reply_markup)
        return ConversationHandler.END

async def internal_add_account(update: Update, context):
    user_id = update.message.chat_id
    phone_number = update.message.text
    if not phone_number.startswith('+'):
        update.message.reply_text("رقم الهاتف غير صحيح. استخدم الصيغة الدولية (+1234567890).")
        return ACCOUNT
    internal_report_data[user_id]['account_number'] = phone_number
    client = TelegramClient(phone_number, TELETHON_API_ID, TELETHON_API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        try:
            phone_code_hash = await client.send_code_request(phone_number)
            internal_report_data[user_id]['phone_code_hash'] = phone_code_hash.phone_code_hash
            update.message.reply_text("يرجى إدخال الكود المرسل إلى حسابك:")
            return CODE
        except Exception as e:
            update.message.reply_text(f"حدث خطأ: {e}")
            return ConversationHandler.END
    else:
        internal_report_data[user_id].setdefault('accounts', []).append(phone_number)
        update.message.reply_text("تم إضافة الحساب بنجاح!")
        return ConversationHandler.END

async def internal_verify_code(update: Update, context):
    user_id = update.message.chat_id
    code = update.message.text
    client = TelegramClient(internal_report_data[user_id]['account_number'], TELETHON_API_ID, TELETHON_API_HASH)
    await client.connect()
    try:
        await client.sign_in(internal_report_data[user_id]['account_number'], code=code, phone_code_hash=internal_report_data[user_id]['phone_code_hash'])
        internal_report_data[user_id].setdefault('accounts', []).append(internal_report_data[user_id]['account_number'])
        update.message.reply_text("تم إضافة الحساب بنجاح!")
        return ConversationHandler.END
    except SessionPasswordNeededError:
        update.message.reply_text("الحساب يحتاج كلمة مرور ثنائية، أدخلها:")
        return PASSWORD
    except Exception as e:
        update.message.reply_text(f"الكود غير صحيح: {e}")
        return CODE

async def internal_enter_password(update: Update, context):
    user_id = update.message.chat_id
    password = update.message.text
    client = TelegramClient(internal_report_data[user_id]['account_number'], TELETHON_API_ID, TELETHON_API_HASH)
    await client.connect()
    try:
        await client.sign_in(password=password)
        internal_report_data[user_id].setdefault('accounts', []).append(internal_report_data[user_id]['account_number'])
        update.message.reply_text("تم إضافة الحساب بنجاح!")
        return ConversationHandler.END
    except Exception as e:
        update.message.reply_text(f"كلمة المرور غير صحيحة: {e}")
        return PASSWORD

def internal_add_group(update: Update, context):
    user_id = update.message.chat_id
    group_link = update.message.text
    if not group_link.startswith('https://t.me/'):
        update.message.reply_text("رابط المجموعة/القناة غير صحيح.")
        return GROUP
    internal_report_data[user_id]['group_link'] = group_link
    update.message.reply_text("تمت إضافة المجموعة/القناة بنجاح!")
    return ConversationHandler.END

def internal_set_messages(update: Update, context):
    user_id = update.message.chat_id
    messages = update.message.text.split('\n')
    valid_messages = [msg for msg in messages if msg.startswith('https://t.me/')]
    if not valid_messages:
        update.message.reply_text("يرجى إدخال روابط رسائل صحيحة.")
        return MESSAGES
    internal_report_data[user_id]['messages'] = valid_messages
    update.message.reply_text("تم تعيين الرسائل بنجاح!")
    return ConversationHandler.END

def internal_set_report_type(update: Update, context):
    user_id = update.message.chat_id
    keyboard = [
        [InlineKeyboardButton("إزعاج", callback_data='internal_report_type_spam')],
        [InlineKeyboardButton("عنف", callback_data='internal_report_type_violence')],
        [InlineKeyboardButton("إباحية", callback_data='internal_report_type_pornography')],
        [InlineKeyboardButton("إساءة للأطفال", callback_data='internal_report_type_child_abuse')],
        [InlineKeyboardButton("حقوق النشر", callback_data='internal_report_type_copyright')],
        [InlineKeyboardButton("مخدرات", callback_data='internal_report_type_drugs')],
        [InlineKeyboardButton("أخرى", callback_data='internal_report_type_other')],
        [InlineKeyboardButton("مزيف", callback_data='internal_report_type_fake')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("يرجى اختيار نوع الإبلاغ:", reply_markup=reply_markup)
    return REPORT_TYPE

def internal_set_report_type_choice(update: Update, context):
    query = update.callback_query
    user_id = query.message.chat_id
    report_type = query.data.split('_')[2]
    internal_report_data[user_id]['report_type'] = report_type
    query.message.reply_text(f"تم تعيين نوع الإبلاغ إلى {report_type}")
    return ConversationHandler.END

def internal_set_report_message(update: Update, context):
    user_id = update.message.chat_id
    message = update.message.text
    if len(message) < 5:
        update.message.reply_text("رسالة الإبلاغ قصيرة جدًا.")
        return REPORT_MESSAGE
    internal_report_data[user_id]['report_message'] = message
    update.message.reply_text("تم تعيين رسالة الإبلاغ بنجاح!")
    return ConversationHandler.END

def internal_set_report_count(update: Update, context):
    user_id = update.message.chat_id
    try:
        count = int(update.message.text)
        if count <= 0 or count > 1000:
            update.message.reply_text("يرجى إدخال عدد بين 1 و1000.")
            return REPORT_COUNT
        internal_report_data[user_id]['report_count'] = count
        update.message.reply_text("تم تعيين عدد الإبلاغات بنجاح!")
        return ConversationHandler.END
    except ValueError:
        update.message.reply_text("يرجى إدخال رقم صحيح.")
        return REPORT_COUNT

def internal_toggle_protection(update: Update, context):
    user_id = update.message.chat_id
    keyboard = [
        [InlineKeyboardButton("تفعيل الحماية", callback_data='internal_enable_protection'),
         InlineKeyboardButton("تعطيل الحماية", callback_data='internal_disable_protection')],
        [InlineKeyboardButton("تعيين التأخير", callback_data='internal_set_delay')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    status = "مفعلة" if internal_report_data[user_id]['protection_enabled'] else "معطلة"
    update.message.reply_text(f"حالة الحماية: {status}\nاختر خيارًا:", reply_markup=reply_markup)
    return PROTECTION

def internal_protection_handler(update: Update, context):
    query = update.callback_query
    query.answer()
    user_id = query.message.chat_id
    if query.data == 'internal_enable_protection':
        internal_report_data[user_id]['protection_enabled'] = True
        context.bot.send_message(user_id, "تم تفعيل الحماية! الإبلاغ سيكون أبطأ.")
    elif query.data == 'internal_disable_protection':
        internal_report_data[user_id]['protection_enabled'] = False
        context.bot.send_message(user_id, "تم تعطيل الحماية! الإبلاغ سيكون أسرع.")
    elif query.data == 'internal_set_delay':
        context.bot.send_message(user_id, "أدخل التأخير بين الإبلاغات (ثوانٍ):")
        return PROTECTION
    return ConversationHandler.END

def internal_set_delay(update: Update, context):
    user_id = update.message.chat_id
    try:
        delay = int(update.message.text)
        if delay < 1 or delay > 60:
            update.message.reply_text("يرجى إدخال تأخير بين 1 و60 ثانية.")
            return PROTECTION
        internal_report_data[user_id]['delay_between_reports'] = delay
        update.message.reply_text(f"تم تعيين التأخير إلى {delay} ثانية!")
        return ConversationHandler.END
    except ValueError:
        update.message.reply_text("يرجى إدخال رقم صحيح.")
        return PROTECTION

async def internal_start_report(update: Update, context):
    user_id = update.message.chat_id
    required_keys = ['report_count', 'report_message', 'messages', 'accounts', 'group_link', 'report_type']
    if not all(key in internal_report_data[user_id] for key in required_keys):
        update.message.reply_text("يرجى تعيين جميع المعطيات قبل بدء الإبلاغ.")
        return ConversationHandler.END

    report_count = internal_report_data[user_id]['report_count']
    report_message = internal_report_data[user_id]['report_message']
    messages = internal_report_data[user_id]['messages']
    accounts = internal_report_data[user_id]['accounts']
    report_type = internal_report_data[user_id]['report_type']

    report_reason_mapping = {
        'spam': InputReportReasonSpam(),
        'violence': InputReportReasonViolence(),
        'pornography': InputReportReasonPornography(),
        'child_abuse': InputReportReasonChildAbuse(),
        'copyright': InputReportReasonCopyright(),
        'drugs': InputReportReasonDrugs(),
        'other': InputReportReasonOther(),
        'fake': InputReportReasonFake()
    }
    reason = report_reason_mapping.get(report_type, InputReportReasonOther())

    successful_reports = 0
    failed_reports = 0
    internal_report_data[user_id]['stop_report'] = False

    status_message = context.bot.send_message(user_id, f"جاري الإبلاغ...\nناجح: {successful_reports}\nفاشل: {failed_reports}")

    for account in accounts:
        if internal_report_data[user_id]['stop_report']:
            break
        client = TelegramClient(account, TELETHON_API_ID, TELETHON_API_HASH)
        try:
            await client.connect()
            if not await client.is_user_authorized():
                continue
            for message_link in messages:
                if internal_report_data[user_id]['stop_report'] or successful_reports + failed_reports >= report_count:
                    break
                try:
                    parts = message_link.split('/')
                    if len(parts) < 5:
                        continue
                    username = parts[-2]
                    message_id = int(parts[-1])
                    async for message in client.iter_messages(username, ids=message_id):
                        await client(ReportPeerRequest(
                            peer=PeerUser(user_id=message.from_id.user_id),
                            reason=reason,
                            message=report_message
                        ))
                        successful_reports += 1
                except FloodWaitError as e:
                    failed_reports += 1
                    logger.warning(f"تم حظر الإبلاغ مؤقتًا لـ {account}: {e.seconds} ثانية")
                    await asyncio.sleep(e.seconds)
                except Exception as e:
                    failed_reports += 1
                    logger.error(f"خطأ أثناء الإبلاغ: {e}")

                context.bot.edit_message_text(
                    chat_id=user_id,
                    message_id=status_message.message_id,
                    text=f"جاري الإبلاغ...\nناجح: {successful_reports}\nفاشل: {failed_reports}"
                )
                delay = internal_report_data[user_id]['delay_between_reports'] + random.uniform(0, 2) if internal_report_data[user_id]['protection_enabled'] else random.uniform(0, 1)
                await asyncio.sleep(delay)
            await client.disconnect()
        except Exception as e:
            logger.error(f"خطأ في الاتصال بحساب {account}: {e}")
            failed_reports += 1

    context.bot.edit_message_text(
        chat_id=user_id,
        message_id=status_message.message_id,
        text=f"تم انتهاء الإبلاغ!\nناجح: {successful_reports}\nفاشل: {failed_reports}"
    )
    return ConversationHandler.END

def internal_stop_report(update: Update, context):
    user_id = update.message.chat_id
    internal_report_data[user_id]['stop_report'] = True
    update.message.reply_text("تم إيقاف الإبلاغ!")
    return ConversationHandler.END

def internal_view_info(update: Update, context):
    user_id = update.message.chat_id
    data = internal_report_data.get(user_id, {})
    info = (
        f"عدد الإبلاغات: {data.get('report_count', 0)}\n"
        f"رسالة الإبلاغ: {data.get('report_message', '')}\n"
        f"الرسائل: {data.get('messages', [])}\n"
        f"الحسابات: {data.get('accounts', [])}\n"
        f"رابط المجموعة: {data.get('group_link', '')}\n"
        f"نوع الإبلاغ: {data.get('report_type', '')}\n"
        f"الحماية: {'مفعلة' if data.get('protection_enabled', False) else 'معطلة'}\n"
        f"التأخير: {data.get('delay_between_reports', 5)} ثانية"
    )
    update.message.reply_text(info)
    return ConversationHandler.END

def run_internal_report(chat_id):
    updater = Updater(API_TOKEN, use_context=True)
    dp = updater.dispatcher
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(internal_button, pattern='internal_.*')],
        states={
            ACCOUNT: [MessageHandler(Filters.text & ~Filters.command, internal_add_account)],
            CODE: [MessageHandler(Filters.text & ~Filters.command, internal_verify_code)],
            PASSWORD: [MessageHandler(Filters.text & ~Filters.command, internal_enter_password)],
            GROUP: [MessageHandler(Filters.text & ~Filters.command, internal_add_group)],
            MESSAGES: [MessageHandler(Filters.text & ~Filters.command, internal_set_messages)],
            REPORT_TYPE: [CallbackQueryHandler(internal_set_report_type_choice, pattern='internal_report_type_.*'),
                          MessageHandler(Filters.text & ~Filters.command, internal_set_report_type)],
            REPORT_MESSAGE: [MessageHandler(Filters.text & ~Filters.command, internal_set_report_message)],
            REPORT_COUNT: [MessageHandler(Filters.text & ~Filters.command, internal_set_report_count)],
            START_REPORT: [MessageHandler(Filters.text & ~Filters.command, internal_start_report)],
            STOP_REPORT: [MessageHandler(Filters.text & ~Filters.command, internal_stop_report)],
            INFO: [MessageHandler(Filters.text & ~Filters.command, internal_view_info)],
            PROTECTION: [CallbackQueryHandler(internal_protection_handler, pattern='internal_(enable|disable)_protection|internal_set_delay'),
                         MessageHandler(Filters.text & ~Filters.command, internal_set_delay)]
        },
        fallbacks=[CommandHandler('start', lambda update, context: send_welcome(update.message))]
    )
    dp.add_handler(conv_handler)
    updater.start_polling()
    updater.idle()

# وظائف الشد الخارجي
def send_report(user_id):
    if not bot_enabled:
        bot.send_message(user_id, DECORATION.format("البوت معطل حاليًا"))
        return
    if sending_in_progress.get(user_id, False):
        bot.send_message(user_id, DECORATION.format("عملية الإرسال جارية بالفعل"))
        return
    sending_in_progress[user_id] = True
    stop_sending[user_id] = False

    if not all([report_channel_or_group_id.get(user_id), report_subject.get(user_id), report_message.get(user_id)]):
        bot.send_message(user_id, DECORATION.format("يجب تعيين البريد والموضوع والرسالة أولاً"))
        sending_in_progress[user_id] = False
        return

    accounts = user_email_accounts.get(user_id, [])
    if not accounts:
        bot.send_message(user_id, DECORATION.format("لا توجد حسابات إيميل مضافة"))
        sending_in_progress[user_id] = False
        return

    target_count = message_count.get(user_id, 0)
    max_count = 5000 if is_vip(user_id) else 500
    if target_count <= 0 or target_count > max_count:
        bot.send_message(user_id, DECORATION.format(f"عدد الرسائل يجب أن يكون بين 1 و {max_count}"))
        sending_in_progress[user_id] = False
        return

    successful_sends = 0
    failed_sends = 0
    progress_bar = "⫷✧ "
    status_message = bot.send_message(user_id, DECORATION.format(f"تم بدء الإرسال\n{progress_bar}\n- ناجح: {successful_sends}\n- فاشل: {failed_sends}"))

    while successful_sends + failed_sends < target_count:
        for account in accounts:
            if stop_sending.get(user_id, False):
                bot.send_message(user_id, DECORATION.format("تم إيقاف الإرسال"))
                sending_in_progress[user_id] = False
                return
            if successful_sends + failed_sends >= target_count:
                break
            try:
                if send_email(
                    account['email'],
                    account['password'],
                    report_subject[user_id],
                    report_message[user_id],
                    report_channel_or_group_id[user_id],
                    report_image.get(user_id)
                ):
                    successful_sends += 1
                    user_points[user_id] = user_points.get(user_id, 0) + 1
                    if user_points[user_id] >= 10000 and user_id not in vip_users:
                        vip_users.append(user_id)
                        user_points[user_id] -= 10000
                        bot.send_message(user_id, DECORATION.format("مبروك! صرت VIP ليوم واحد بـ 10,000 نقطة"))
                        threading.Timer(24 * 60 * 60, lambda: vip_users.remove(user_id) if user_id in vip_users else None).start()
                else:
                    failed_sends += 1
            except Exception as e:
                failed_sends += 1
                log_error(user_id, e)

            progress = (successful_sends + failed_sends) / target_count * 100
            progress_bar = "⫷✧ " + "✧" * int(progress / 10)
            bot.edit_message_text(
                chat_id=user_id,
                message_id=status_message.message_id,
                text=DECORATION.format(f"تقدم الإرسال: {progress:.1f}%\n{progress_bar}\n- ناجح: {successful_sends}\n- فاشل: {failed_sends}")
            )
            time.sleep(max(send_interval.get(user_id, 1), 1))

    sending_in_progress[user_id] = False
    success_rate = (successful_sends / (successful_sends + failed_sends) * 100) if (successful_sends + failed_sends) > 0 else 0
    bot.edit_message_text(
        chat_id=user_id,
        message_id=status_message.message_id,
        text=DECORATION.format(f"تم إنهاء الإرسال\n- ناجح: {successful_sends}\n- فاشل: {failed_sends}\n- معدل النجاح: {success_rate:.1f}%")
    )
    send_notification(user_id, "انتهى الإرسال")

def schedule_send_report(user_id, send_time):
    send_schedule[user_id] = send_time
    bot.send_message(user_id, DECORATION.format(f"تم جدولة الإرسال في {send_time}"))

def check_and_send_scheduled_report():
    while True:
        current_time = datetime.now()
        for user_id, send_time in list(send_schedule.items()):
            if send_time and current_time >= send_time:
                threading.Thread(target=send_report, args=(user_id,)).start()
                del send_schedule[user_id]
        time.sleep(60)

# معالجات البوت الرئيسي
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message, is_back_button=False):
    user_id = message.from_user.id
    all_users.add(user_id)
    if not bot_enabled and user_id != DEVELOPER_ID:
        bot.send_message(user_id, DECORATION.format("البوت معطل حاليًا"))
        return
    if user_id in banned_users:
        bot.send_message(user_id, DECORATION.format("تم حظرك من استخدام البوت"))
        return
    if not is_authorized(user_id) and not is_back_button:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("المطور", url=f"tg://user?id={DEVELOPER_ID}"))
        bot.send_message(message.chat.id, DECORATION.format("أنت عضو، راسل المطور للترقية!"), reply_markup=markup)
    else:
        keyboard = types.InlineKeyboardMarkup()
        keyboard.row(
            types.InlineKeyboardButton(DECORATION.format("إضافة الحسابات"), callback_data='add_accounts'),
            types.InlineKeyboardButton(DECORATION.format("إضافة حسابات متعددة"), callback_data='add_multiple_accounts')
        )
        keyboard.row(
            types.InlineKeyboardButton(DECORATION.format("عرض الحسابات"), callback_data='view_accounts'),
            types.InlineKeyboardButton(DECORATION.format("تعيين البريد"), callback_data='set_email')
        )
        keyboard.row(
            types.InlineKeyboardButton(DECORATION.format("تعيين الموضوع"), callback_data='set_subject'),
            types.InlineKeyboardButton(DECORATION.format("تعيين الرسالة"), callback_data='set_message')
        )
        keyboard.row(
            types.InlineKeyboardButton(DECORATION.format("تعيين الصورة"), callback_data='set_image'),
            types.InlineKeyboardButton(DECORATION.format("تعيين عدد الإرسال"), callback_data='set_message_count')
        )
        keyboard.row(
            types.InlineKeyboardButton(DECORATION.format("تعيين الفترة الزمنية"), callback_data='set_send_interval'),
            types.InlineKeyboardButton(DECORATION.format("حفظ كليشة"), callback_data='save_template')
        )
        keyboard.row(
            types.InlineKeyboardButton(DECORATION.format("تحميل كليشة"), callback_data='load_template'),
            types.InlineKeyboardButton(DECORATION.format("عرض النقاط"), callback_data='view_points')
        )
        keyboard.row(
            types.InlineKeyboardButton(DECORATION.format("بدء الإرسال"), callback_data='start_sending'),
            types.InlineKeyboardButton(DECORATION.format("إيقاف الإرسال"), callback_data='stop_sending')
        )
        keyboard.add(types.InlineKeyboardButton(DECORATION.format("جدولة الإرسال"), callback_data='schedule_send'))
        if is_vip(user_id):
            keyboard.add(types.InlineKeyboardButton(DECORATION.format("قسم الشد الداخلي"), callback_data='internal_section'))
        if is_developer(user_id):
            keyboard.add(types.InlineKeyboardButton(DECORATION.format("لوحة التحكم"), callback_data='developer_panel'))
        bot.send_message(message.chat.id, DECORATION.format("أوامر بوت الشد الخارجي"), reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    user_id = call.from_user.id
    if not is_authorized(user_id):
        return
    try:
        if call.data == 'internal_section' and is_vip(user_id):
            threading.Thread(target=run_internal_report, args=(call.message.chat.id,), daemon=True).start()
            bot.send_message(call.message.chat.id, DECORATION.format("تم فتح قسم الشد الداخلي!"))
        elif call.data == 'developer_panel' and is_developer(user_id):
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(
                types.InlineKeyboardButton(DECORATION.format("حظر مستخدم"), callback_data='ban_user'),
                types.InlineKeyboardButton(DECORATION.format("إلغاء حظر مستخدم"), callback_data='unban_user')
            )
            keyboard.row(
                types.InlineKeyboardButton(DECORATION.format("إعطاء VIP"), callback_data='give_vip'),
                types.InlineKeyboardButton(DECORATION.format("سحب VIP"), callback_data='remove_vip')
            )
            keyboard.row(
                types.InlineKeyboardButton(DECORATION.format("إذاعة عامة"), callback_data='broadcast'),
                types.InlineKeyboardButton(DECORATION.format("تشغيل/تعطيل البوت"), callback_data='toggle_bot')
            )
            keyboard.row(
                types.InlineKeyboardButton(DECORATION.format("عرض إحصائيات المستخدمين"), callback_data='user_stats'),
                types.InlineKeyboardButton(DECORATION.format("إعادة تعيين نقاط مستخدم"), callback_data='reset_points')
            )
            bot.send_message(call.message.chat.id, DECORATION.format("لوحة تحكم المطور"), reply_markup=keyboard)
        elif call.data == 'add_accounts':
            msg = bot.send_message(call.message.chat.id, DECORATION.format("أرسل الإيميل والباسورد (email:password)"))
            bot.register_next_step_handler(msg, add_email_account)
        elif call.data == 'add_multiple_accounts':
            msg = bot.send_message(call.message.chat.id, DECORATION.format("أرسل قائمة (email,password) بفاصلة"))
            bot.register_next_step_handler(msg, add_multiple_email_accounts)
        elif call.data == 'view_accounts':
            back_button = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(DECORATION.format("رجوع"), callback_data='back_to_main'))
            if user_id in user_email_accounts:
                accounts = user_email_accounts[user_id]
                keyboard = types.InlineKeyboardMarkup()
                for idx, account in enumerate(accounts):
                    keyboard.row(
                        types.InlineKeyboardButton(account['email'], callback_data=f'account_{idx}'),
                        types.InlineKeyboardButton(DECORATION.format("حذف"), callback_data=f'delete_account_{idx}')
                    )
                keyboard.add(types.InlineKeyboardButton(DECORATION.format("رجوع"), callback_data='back_to_main'))
                bot.send_message(call.message.chat.id, DECORATION.format("الحسابات المضافة:"), reply_markup=keyboard)
            else:
                bot.send_message(call.message.chat.id, DECORATION.format("لا توجد حسابات مضافة"), reply_markup=back_button)
        elif call.data == 'set_email':
            msg = bot.send_message(call.message.chat.id, DECORATION.format("أرسل البريد الآن"))
            bot.register_next_step_handler(msg, set_email)
        elif call.data == 'set_subject':
            msg = bot.send_message(call.message.chat.id, DECORATION.format("أرسل الموضوع الآن"))
            bot.register_next_step_handler(msg, set_subject)
        elif call.data == 'set_message':
            msg = bot.send_message(call.message.chat.id, DECORATION.format("أرسل الرسالة الآن"))
            bot.register_next_step_handler(msg, set_message)
        elif call.data == 'set_image':
            msg = bot.send_message(call.message.chat.id, DECORATION.format("أرسل الصورة الآن"))
            bot.register_next_step_handler(msg, set_image)
        elif call.data == 'set_message_count':
            msg = bot.send_message(call.message.chat.id, DECORATION.format("أرسل عدد مرات الإرسال"))
            bot.register_next_step_handler(msg, set_message_count)
        elif call.data == 'set_send_interval':
            msg = bot.send_message(call.message.chat.id, DECORATION.format("أرسل الفترة الزمنية (ثواني)"))
            bot.register_next_step_handler(msg, set_send_interval)
        elif call.data == 'start_sending':
            threading.Thread(target=send_report, args=(user_id,)).start()
        elif call.data == 'stop_sending':
            stop_sending[user_id] = True
        elif call.data == 'schedule_send':
            msg = bot.send_message(call.message.chat.id, DECORATION.format("أرسل الوقت (YYYY-MM-DD HH:MM:SS)"))
            bot.register_next_step_handler(msg, schedule_send)
        elif call.data == 'save_template':
            msg = bot.send_message(call.message.chat.id, DECORATION.format("أرسل اسم الكليشة والنص (اسم:نص)"))
            bot.register_next_step_handler(msg, save_template)
        elif call.data == 'load_template':
            back_button = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(DECORATION.format("رجوع"), callback_data='back_to_main'))
            if user_id in templates and templates[user_id]:
                keyboard = types.InlineKeyboardMarkup()
                for name in templates[user_id]:
                    keyboard.add(types.InlineKeyboardButton(name, callback_data=f"template_{name}"))
                keyboard.add(types.InlineKeyboardButton(DECORATION.format("رجوع"), callback_data='back_to_main'))
                bot.send_message(call.message.chat.id, DECORATION.format("اختر الكليشة:"), reply_markup=keyboard)
            else:
                bot.send_message(call.message.chat.id, DECORATION.format("لا توجد كليشات محفوظة"), reply_markup=back_button)
        elif call.data.startswith('template_'):
            template_name = call.data.split('_')[1]
            report_message[user_id] = templates[user_id][template_name]
            bot.send_message(call.message.chat.id, DECORATION.format("تم تحميل الكليشة"))
        elif call.data == 'view_points':
            points = user_points.get(user_id, 0)
            back_button = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(DECORATION.format("رجوع"), callback_data='back_to_main'))
            bot.send_message(call.message.chat.id, DECORATION.format(f"نقاطك: {points}\nاجمع 10,000 نقطة وتصير VIP ليوم واحد!"), reply_markup=back_button)
        elif call.data == 'back_to_main':
            send_welcome(call.message, is_back_button=True)
        elif call.data.startswith('delete_account_'):
            idx = int(call.data.split('_')[2])
            user_email_accounts[user_id].pop(idx)
            bot.send_message(call.message.chat.id, DECORATION.format("تم حذف الحساب"))
        elif call.data == 'ban_user':
            msg = bot.send_message(call.message.chat.id, DECORATION.format("أرسل معرف المستخدم لحظره"))
            bot.register_next_step_handler(msg, ban_user)
        elif call.data == 'unban_user':
            msg = bot.send_message(call.message.chat.id, DECORATION.format("أرسل معرف المستخدم لإلغاء حظره"))
            bot.register_next_step_handler(msg, unban_user)
        elif call.data == 'give_vip':
            msg = bot.send_message(call.message.chat.id, DECORATION.format("أرسل معرف المستخدم لإعطائه VIP"))
            bot.register_next_step_handler(msg, give_vip)
        elif call.data == 'remove_vip':
            msg = bot.send_message(call.message.chat.id, DECORATION.format("أرسل معرف المستخدم لسحب VIP منه"))
            bot.register_next_step_handler(msg, remove_vip)
        elif call.data == 'broadcast':
            msg = bot.send_message(call.message.chat.id, DECORATION.format("أرسل الرسالة للإذاعة العامة"))
            bot.register_next_step_handler(msg, broadcast)
        elif call.data == 'toggle_bot':
            global bot_enabled
            bot_enabled = not bot_enabled
            status = "مفعل" if bot_enabled else "معطل"
            bot.send_message(call.message.chat.id, DECORATION.format(f"تم تغيير حالة البوت إلى: {status}"))
        elif call.data == 'user_stats':
            stats = "\n".join([f"المستخدم {uid}: {user_points.get(uid, 0)} نقطة" for uid in all_users])
            bot.send_message(call.message.chat.id, DECORATION.format(f"إحصائيات المستخدمين:\n{stats}"))
        elif call.data == 'reset_points':
            msg = bot.send_message(call.message.chat.id, DECORATION.format("أرسل معرف المستخدم لإعادة تعيين نقاطه"))
            bot.register_next_step_handler(msg, reset_points)
    except Exception as e:
        log_error(user_id, e, "فشل في معالجة زر")

def add_email_account(message):
    user_id = message.from_user.id
    try:
        email, password = message.text.split(':')
        if validate_email(email):
            if user_id not in user_email_accounts:
                user_email_accounts[user_id] = []
            user_email_accounts[user_id].append({'email': email, 'password': password})
            bot.send_message(message.chat.id, DECORATION.format("تم إضافة الحساب"))
        else:
            bot.send_message(message.chat.id, DECORATION.format("الإيميل غير صالح"))
    except Exception as e:
        log_error(user_id, e, "فشل في إضافة حساب إيميل")
        bot.send_message(message.chat.id, DECORATION.format("خطأ في التنسيق"))

def add_multiple_email_accounts(message):
    user_id = message.from_user.id
    try:
        accounts = message.text.split('\n')
        if user_id not in user_email_accounts:
            user_email_accounts[user_id] = []
        for account in accounts:
            email, password = account.split(',')
            if validate_email(email):
                user_email_accounts[user_id].append({'email': email, 'password': password})
        bot.send_message(message.chat.id, DECORATION.format("تم إضافة الحسابات"))
    except Exception as e:
        log_error(user_id, e, "فشل في إضافة حسابات متعددة")
        bot.send_message(message.chat.id, DECORATION.format("خطأ في التنسيق"))

def set_email(message):
    user_id = message.from_user.id
    if validate_email(message.text):
        report_channel_or_group_id[user_id] = message.text
        bot.send_message(message.chat.id, DECORATION.format("تم تعيين البريد"))
    else:
        bot.send_message(message.chat.id, DECORATION.format("البريد غير صالح"))

def set_subject(message):
    user_id = message.from_user.id
    report_subject[user_id] = message.text
    bot.send_message(message.chat.id, DECORATION.format("تم تعيين الموضوع"))

def set_message(message):
    user_id = message.from_user.id
    report_message[user_id] = message.text
    bot.send_message(message.chat.id, DECORATION.format("تم تعيين الرسالة"))

def set_image(message):
    user_id = message.from_user.id
    if message.photo:
        file_info = bot.get_file(message.photo[-1].file_id)
        report_image[user_id] = bot.download_file(file_info.file_path)
        bot.send_message(message.chat.id, DECORATION.format("تم تعيين الصورة"))
    else:
        bot.send_message(message.chat.id, DECORATION.format("لا توجد صورة"))

def set_message_count(message):
    user_id = message.from_user.id
    try:
        count = int(message.text)
        max_count = 5000 if is_vip(user_id) else 500
        if 1 <= count <= max_count:
            message_count[user_id] = count
            bot.send_message(message.chat.id, DECORATION.format("تم تعيين العدد"))
        else:
            bot.send_message(message.chat.id, DECORATION.format(f"العدد يجب أن يكون بين 1 و {max_count}"))
    except Exception as e:
        log_error(user_id, e, "فشل في تعيين عدد الإرسال")
        bot.send_message(message.chat.id, DECORATION.format("أدخل رقمًا صحيحًا"))

def set_send_interval(message):
    user_id = message.from_user.id
    try:
        interval = int(message.text)
        if interval >= 1:
            send_interval[user_id] = interval
            bot.send_message(message.chat.id, DECORATION.format("تم تعيين الفترة"))
        else:
            bot.send_message(message.chat.id, DECORATION.format("الحد الأدنى: 1 ثانية"))
    except Exception as e:
        log_error(user_id, e, "فشل في تعيين الفترة الزمنية")
        bot.send_message(message.chat.id, DECORATION.format("أدخل رقمًا صحيحًا"))

def schedule_send(message):
    user_id = message.from_user.id
    try:
        send_time = datetime.strptime(message.text, "%Y-%m-%d %H:%M:%S")
        schedule_send_report(user_id, send_time)
    except Exception as e:
        log_error(user_id, e, "فشل في جدولة الإرسال")
        bot.send_message(message.chat.id, DECORATION.format("خطأ في تنسيق الوقت"))

def save_template(message):
    user_id = message.from_user.id
    try:
        name, text = message.text.split(':')
        if user_id not in templates:
            templates[user_id] = {}
        templates[user_id][name] = text
        bot.send_message(message.chat.id, DECORATION.format("تم حفظ الكليشة"))
    except Exception as e:
        log_error(user_id, e, "فشل في حفظ الكليشة")
        bot.send_message(message.chat.id, DECORATION.format("خطأ في التنسيق"))

def ban_user(message):
    try:
        user_id = int(message.text)
        banned_users.append(user_id)
        bot.send_message(user_id, DECORATION.format("تم حظرك من استخدام البوت"))
        bot.send_message(message.chat.id, DECORATION.format("تم حظر المستخدم"))
    except Exception as e:
        log_error(message.from_user.id, e, "فشل في حظر مستخدم")
        bot.send_message(message.chat.id, DECORATION.format("خطأ في تحديد المستخدم"))

def unban_user(message):
    try:
        user_id = int(message.text)
        banned_users.remove(user_id)
        bot.send_message(user_id, DECORATION.format("تم إلغاء حظرك"))
        bot.send_message(message.chat.id, DECORATION.format("تم إلغاء حظر المستخدم"))
    except Exception as e:
        log_error(message.from_user.id, e, "فشل في إلغاء حظر مستخدم")
        bot.send_message(message.chat.id, DECORATION.format("خطأ في تحديد المستخدم"))

def give_vip(message):
    try:
        user_id = int(message.text)
        vip_users.append(user_id)
        bot.send_message(user_id, DECORATION.format("تمت ترقيتك إلى VIP!"))
        bot.send_message(message.chat.id, DECORATION.format("تم إعطاء VIP للمستخدم"))
    except Exception as e:
        log_error(message.from_user.id, e, "فشل في إعطاء VIP")
        bot.send_message(message.chat.id, DECORATION.format("خطأ في تحديد المستخدم"))

def remove_vip(message):
    try:
        user_id = int(message.text)
        vip_users.remove(user_id)
        bot.send_message(user_id, DECORATION.format("تم سحب عضوية VIP منك"))
        bot.send_message(message.chat.id, DECORATION.format("تم سحب VIP من المستخدم"))
    except Exception as e:
        log_error(message.from_user.id, e, "فشل في سحب VIP")
        bot.send_message(message.chat.id, DECORATION.format("خطأ في تحديد المستخدم"))

def broadcast(message):
    try:
        for uid in all_users:
            bot.send_message(uid, DECORATION.format(message.text))
            time.sleep(1)
        bot.send_message(message.chat.id, DECORATION.format("تم الإذاعة بنجاح"))
    except Exception as e:
        log_error(message.from_user.id, e, "فشل في الإذاعة العامة")

def reset_points(message):
    try:
        user_id = int(message.text)
        user_points[user_id] = 0
        bot.send_message(message.chat.id, DECORATION.format("تم إعادة تعيين نقاط المستخدم"))
    except Exception as e:
        log_error(message.from_user.id, e, "فشل في إعادة تعيين النقاط")
        bot.send_message(message.chat.id, DECORATION.format("خطأ في تحديد المستخدم"))

# بدء الخيط للجدولة
threading.Thread(target=check_and_send_scheduled_report, daemon=True).start()

# بدء البوت
if __name__ == "__main__":
    bot.polling()
