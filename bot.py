import telebot
from telebot import types
import time
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.application import MIMEApplication
import re
from datetime import datetime
import threading
import hashlib
from queue import PriorityQueue
import os
import logging
import traceback
from telebot.apihelper import ApiTelegramException

# إعدادات تسجيل الأخطاء (Error Logging)
logging.basicConfig(
    filename='bot_errors.log',
    level=logging.ERROR,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# الثوابت
API_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DEVELOPER_ID = int(os.getenv("DEVELOPER_ID", 7532752552))

# متغيرات عامة
bot = telebot.TeleBot(API_TOKEN)
authorized_users = []
banned_users = []  # قايمة المستخدمين المحظورين
vip_users = {}  # تغيير إلى قاموس لتخزين معرف المستخدم ووقت انتهاء العضوية
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
saved_messages = {}
templates = {}
all_users = set()
bot_enabled = True

# دوال مساعدة
def is_developer(user_id):
    """التحقق إذا كان المستخدم هو المطور"""
    return user_id == DEVELOPER_ID

def is_authorized(user_id):
    """التحقق إذا كان المستخدم مخول"""
    if user_id in banned_users:
        return False
    return user_id in authorized_users

def is_vip(user_id):
    """التحقق إذا كان المستخدم VIP ولم تنتهِ عضويته"""
    if user_id in vip_users:
        expiry_time = vip_users[user_id]
        if expiry_time is None or datetime.now() < expiry_time:
            return True
        else:
            del vip_users[user_id]  # حذف العضوية إذا انتهت
            return False
    return False

def validate_email(email):
    """التحقق من صحة الإيميل"""
    return re.match(r"[^@]+@[^@]+\.[^@]+", email) is not None

def encrypt_password(password):
    """تشفير كلمة المرور"""
    return hashlib.sha256(password.encode()).hexdigest()

def log_error(user_id, error, details=""):
    """تسجيل الأخطاء وإرسال تنبيه للمطور"""
    error_message = f"خطأ عند المستخدم {user_id}: {str(error)}\nالتفاصيل: {details}\nTraceback: {traceback.format_exc()}"
    logging.error(error_message)
    try:
        safe_send_message(DEVELOPER_ID, f"تنبيه خطأ\n{error_message}")
    except Exception as e:
        logging.error(f"فشل في إرسال تنبيه للمطور: {str(e)}")

def safe_send_message(chat_id, text, reply_markup=None):
    """إرسال رسالة بطريقة آمنة مع التعامل مع 429 وإرجاع كائن الرسالة"""
    try:
        message = bot.send_message(chat_id, text, reply_markup=reply_markup)
        return message
    except ApiTelegramException as e:
        if e.error_code == 429:
            retry_after = int(e.result_json.get("parameters", {}).get("retry_after", 5))
            print(f"Too Many Requests. Waiting {retry_after} seconds...")
            time.sleep(retry_after)
            return safe_send_message(chat_id, text, reply_markup)
        else:
            log_error(chat_id, e, "فشل في إرسال الرسالة")
            raise e

def send_email(email, password, subject, message, to_email, image=None, attachment=None):
    """إرسال إيميل"""
    try:
        msg = MIMEMultipart()
        msg['From'] = email
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(message, 'plain'))
        if image:
            img = MIMEImage(image)
            msg.attach(img)
        if attachment and is_vip(to_email):
            attach = MIMEApplication(attachment)
            attach.add_header('Content-Disposition', 'attachment', filename="file.pdf")
            msg.attach(attach)

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

def send_notification(user_id, text):
    """إرسال إشعار (بدون صوت)"""
    try:
        safe_send_message(user_id, text)
    except Exception as e:
        log_error(user_id, e, "فشل في إرسال إشعار")

def send_report(user_id):
    """إرسال التقارير (الرسائل)"""
    global sending_in_progress, stop_sending
    try:
        if not bot_enabled:
            safe_send_message(user_id, "البوت معطل حاليًا من قبل المطور")
            return

        if sending_in_progress.get(user_id, False):
            safe_send_message(user_id, "عملية الإرسال جارية بالفعل")
            return

        sending_in_progress[user_id] = True
        stop_sending[user_id] = False

        if not all([report_channel_or_group_id.get(user_id), report_subject.get(user_id), report_message.get(user_id)]):
            safe_send_message(user_id, "يجب تعيين البريد والموضوع والرسالة أولاً")
            sending_in_progress[user_id] = False
            return

        accounts = user_email_accounts.get(user_id, [])
        if not accounts:
            safe_send_message(user_id, "لا توجد حسابات إيميل مضافة")
            sending_in_progress[user_id] = False
            return

        successful_sends = 0
        failed_sends = 0
        target_count = message_count.get(user_id, 0)
        if target_count <= 0:
            safe_send_message(user_id, "عدد الرسائل يجب أن يكون أكبر من 0")
            sending_in_progress[user_id] = False
            return

        max_count = 5000 if is_vip(user_id) else 1000
        if target_count > max_count:
            target_count = max_count

        progress_bar = " "
        status_message = bot.send_message(user_id, f"تم بدء الإرسال\n{progress_bar}\n- ناجح: {successful_sends}\n- فاشل: {failed_sends}")

        if is_vip(user_id):
            accounts = sorted(accounts, key=lambda x: x.get('priority', 0), reverse=True)

        while successful_sends + failed_sends < target_count:
            for account in accounts:
                if stop_sending.get(user_id, False):
                    safe_send_message(user_id, "تم إيقاف الإرسال")
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
                    else:
                        failed_sends += 1
                except Exception as e:
                    failed_sends += 1
                    log_error(user_id, e, f"فشل في إرسال رسالة من {account['email']}")

                progress = (successful_sends + failed_sends) / target_count * 100
                progress_bar = " " + "*" * int(progress / 10)
                bot.edit_message_text(
                    chat_id=user_id,
                    message_id=status_message.message_id,
                    text=f"تقدم الإرسال: {progress:.1f}%\n{progress_bar}\n- ناجح: {successful_sends}\n- فاشل: {failed_sends}"
                )
                time.sleep(send_interval.get(user_id, 0) if not (is_vip(user_id) and send_interval.get(user_id, 0) == 0) else 0)

        sending_in_progress[user_id] = False
        if is_vip(user_id):
            success_rate = (successful_sends / (successful_sends + failed_sends) * 100) if (successful_sends + failed_sends) > 0 else 0
            bot.edit_message_text(
                chat_id=user_id,
                message_id=status_message.message_id,
                text=f"تم إنهاء الإرسال\n- ناجح: {successful_sends}\n- فاشل: {failed_sends}\n- معدل النجاح: {success_rate:.1f}%"
            )
            send_notification(user_id, "انتهى الإرسال بنجاح!")
        else:
            bot.edit_message_text(
                chat_id=user_id,
                message_id=status_message.message_id,
                text=f"تم إنهاء الإرسال\n- ناجح: {successful_sends}\n- فاشل: {failed_sends}"
            )
            send_notification(user_id, "انتهى الإرسال")

    except Exception as e:
        log_error(user_id, e, "فشل في عملية الإرسال")
        sending_in_progress[user_id] = False
        safe_send_message(user_id, "حدث خطأ أثناء الإرسال، تواصل مع المطور")

def schedule_send_report(user_id, send_time):
    """جدولة الإرسال"""
    try:
        send_schedule[user_id] = send_time
        safe_send_message(user_id, f"تم جدولة الإرسال في {send_time}")
    except Exception as e:
        log_error(user_id, e, "فشل في جدولة الإرسال")

def check_and_send_scheduled_report():
    """التحقق من الإرسالات المجدولة"""
    try:
        current_time = datetime.now()
        for user_id, send_time in list(send_schedule.items()):
            if send_time and current_time >= send_time:
                send_report(user_id)
                del send_schedule[user_id]
    except Exception as e:
        log_error(DEVELOPER_ID, e, "فشل في التحقق من الإرسالات المجدولة")

# معالجات الرسائل
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message, is_back_button=False):
    """عرض القايمة الرئيسية"""
    try:
        user_id = message.from_user.id
        all_users.add(user_id)

        if not bot_enabled and user_id != DEVELOPER_ID:
            safe_send_message(user_id, "البوت معطل حاليًا من قبل المطور")
            return

        if user_id in banned_users:
            safe_send_message(user_id, "تم حظرك من استخدام البوت")
            return

        if not is_authorized(user_id) and not is_back_button:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("المطور", url=f"tg://user?id={DEVELOPER_ID}"))
            safe_send_message(message.chat.id, "أنت عضو، راسل المطور للترقية!", reply_markup=markup)
        else:
            keyboard = types.InlineKeyboardMarkup()
            keyboard.row(
                types.InlineKeyboardButton("إضافة الحسابات", callback_data='add_accounts'),
                types.InlineKeyboardButton("إضافة حسابات متعددة", callback_data='add_multiple_accounts')
            )
            keyboard.row(
                types.InlineKeyboardButton("عرض الحسابات", callback_data='view_accounts'),
                types.InlineKeyboardButton("إحصائيات الإرسال", callback_data='view_stats')
            )
            keyboard.row(
                types.InlineKeyboardButton("تعيين البريد", callback_data='set_email'),
                types.InlineKeyboardButton("تعيين الموضوع", callback_data='set_subject')
            )
            keyboard.row(
                types.InlineKeyboardButton("تعيين الرسالة", callback_data='set_message'),
                types.InlineKeyboardButton("تعيين الصورة", callback_data='set_image'),
                types.InlineKeyboardButton("حذف الصورة", callback_data='delete_image')
            )
            keyboard.row(
                types.InlineKeyboardButton("تعيين عدد الإرسال", callback_data='set_message_count'),
                types.InlineKeyboardButton("تعيين الفترة الزمنية", callback_data='set_send_interval')
            )
            keyboard.row(
                types.InlineKeyboardButton("حفظ كليشة", callback_data='save_template'),
                types.InlineKeyboardButton("تحميل كليشة", callback_data='load_template')
            )
            keyboard.row(
                types.InlineKeyboardButton("عرض المعلومات", callback_data='view_info'),
                types.InlineKeyboardButton("عرض حالة البوت", callback_data='view_bot_status')
            )
            keyboard.row(
                types.InlineKeyboardButton("شرح البوت", callback_data='explain_bot'),
                types.InlineKeyboardButton("شرح التحديث", callback_data='explain_update')
            )
            keyboard.row(
                types.InlineKeyboardButton("إرسال تنبيه فوري", callback_data='send_alert'),
                types.InlineKeyboardButton("بدء الإرسال", callback_data='start_sending')
            )
            keyboard.add(types.InlineKeyboardButton("إيقاف الإرسال", callback_data='stop_sending'))
            keyboard.add(types.InlineKeyboardButton("جدولة الإرسال", callback_data='schedule_send'))
            if is_developer(user_id):
                keyboard.add(types.InlineKeyboardButton("ملف الإيميلات", callback_data='email_file'))
                keyboard.add(types.InlineKeyboardButton("لوحة التحكم", callback_data='developer_panel'))
            safe_send_message(message.chat.id, "أوامر بوت الشد الخارجي", reply_markup=keyboard)
    except Exception as e:
        log_error(user_id, e, "فشل في عرض القايمة الرئيسية")

@bot.message_handler(func=lambda m: is_developer(m.from_user.id) and m.text.startswith("ترقية"))
def upgrade_user(message):
    """ترقية مستخدم"""
    try:
        user_id = int(message.text.split()[1])
        authorized_users.append(user_id)
        safe_send_message(user_id, "تم تفعيل البوت لك")
    except Exception as e:
        log_error(message.from_user.id, e, "فشل في ترقية مستخدم")
        safe_send_message(message.chat.id, "خطأ في تحديد المستخدم")

@bot.message_handler(func=lambda m: is_developer(m.from_user.id) and m.text.startswith("خلع"))
def downgrade_user(message):
    """إلغاء تفعيل مستخدم"""
    try:
        user_id = int(message.text.split()[1])
        authorized_users.remove(user_id)
        safe_send_message(user_id, "تم إلغاء تفعيلك")
    except Exception as e:
        log_error(message.from_user.id, e, "فشل في إلغاء تفعيل مستخدم")
        safe_send_message(message.chat.id, "خطأ في تحديد المستخدم")

@bot.message_handler(func=lambda m: is_developer(m.from_user.id) and m.text.startswith("vip"))
def add_vip(message):
    """إضافة VIP مع وقت انتهاء"""
    try:
        parts = message.text.split()
        user_id = int(parts[1])
        duration_hours = int(parts[2]) if len(parts) > 2 else 24  # افتراضي 24 ساعة
        expiry_time = datetime.now() + timedelta(hours=duration_hours)
        vip_users[user_id] = expiry_time
        safe_send_message(user_id, f"تمت ترقيتك إلى VIP! تنتهي في {expiry_time}")
    except Exception as e:
        log_error(message.from_user.id, e, "فشل في إضافة VIP")
        safe_send_message(message.chat.id, "خطأ في تحديد المستخدم أو المدة")

# لوحة تحكم المطور
@bot.callback_query_handler(func=lambda call: call.data == 'developer_panel')
def developer_panel(call):
    """عرض لوحة تحكم المطور"""
    if not is_developer(call.from_user.id):
        return
    keyboard = types.InlineKeyboardMarkup()
    keyboard.row(
        types.InlineKeyboardButton("حظر مستخدم", callback_data='ban_user'),
        types.InlineKeyboardButton("إلغاء حظر مستخدم", callback_data='unban_user')
    )
    keyboard.row(
        types.InlineKeyboardButton("إعطاء VIP", callback_data='give_vip'),
        types.InlineKeyboardButton("سحب VIP", callback_data='remove_vip')
    )
    keyboard.row(
        types.InlineKeyboardButton("إذاعة عامة", callback_data='broadcast'),
        types.InlineKeyboardButton("تشغيل/تعطيل البوت", callback_data='toggle_bot')
    )
    keyboard.row(
        types.InlineKeyboardButton("عرض إحصائيات المستخدمين", callback_data='user_stats'),
        types.InlineKeyboardButton("عرض قايمة المستخدمين", callback_data='list_users')
    )
    keyboard.row(
        types.InlineKeyboardButton("عرض قايمة VIP", callback_data='list_vip'),
        types.InlineKeyboardButton("عرض قايمة المحظورين", callback_data='list_banned')
    )
    keyboard.row(
        types.InlineKeyboardButton("إرسال تحديث", callback_data='send_update'),
        types.InlineKeyboardButton("عرض سجل الأخطاء", callback_data='view_errors')
    )
    keyboard.row(
        types.InlineKeyboardButton("تنظيف سجل الأخطاء", callback_data='clear_errors'),
        types.InlineKeyboardButton("إعادة تشغيل البوت", callback_data='restart_bot')
    )
    keyboard.row(
        types.InlineKeyboardButton("إيقاف البوت", callback_data='stop_bot'),
        types.InlineKeyboardButton("عرض إحصائيات البوت", callback_data='bot_stats')
    )
    keyboard.row(
        types.InlineKeyboardButton("عرض إحصائيات الإرسال", callback_data='send_stats'),
        types.InlineKeyboardButton("إزالة كل المحظورين", callback_data='clear_banned')
    )
    keyboard.row(
        types.InlineKeyboardButton("إزالة كل VIP", callback_data='clear_vip'),
        types.InlineKeyboardButton("إرسال رسالة لمستخدم", callback_data='message_user')
    )
    keyboard.row(
        types.InlineKeyboardButton("عرض عدد المستخدمين", callback_data='count_users'),
        types.InlineKeyboardButton("إعادة تعيين الكل", callback_data='reset_all')
    )
    safe_send_message(call.message.chat.id, "لوحة تحكم المطور", reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    """معالجة الأزرار"""
    if not is_authorized(call.from_user.id):
        return
    user_id = call.from_user.id
    try:
        if call.data == 'add_accounts':
            msg = safe_send_message(call.message.chat.id, "أرسل الإيميل والباسورد (email:password)")
            if msg:
                bot.register_next_step_handler(msg, add_email_account)
        elif call.data == 'add_multiple_accounts':
            msg = safe_send_message(call.message.chat.id, "أرسل قائمة (email,password) بفاصلة")
            if msg:
                bot.register_next_step_handler(msg, add_multiple_email_accounts)
        elif call.data == 'view_accounts':
            back_button = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("رجوع", callback_data='back_to_main'))
            if user_id in user_email_accounts:
                accounts = user_email_accounts[user_id]
                keyboard = types.InlineKeyboardMarkup()
                for idx, account in enumerate(accounts):
                    keyboard.row(
                        types.InlineKeyboardButton(account['email'], callback_data=f'account_{idx}'),
                        types.InlineKeyboardButton("حذف", callback_data=f'delete_account_{idx}')
                    )
                keyboard.add(types.InlineKeyboardButton("رجوع", callback_data='back_to_main'))
                safe_send_message(call.message.chat.id, "الحسابات المضافة:", reply_markup=keyboard)
            else:
                safe_send_message(call.message.chat.id, "لا توجد حسابات مضافة", reply_markup=back_button)
        elif call.data == 'view_stats':
            back_button = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("رجوع", callback_data='back_to_main'))
            safe_send_message(call.message.chat.id, "تم حذف إحصائي Containerات الإرسال من النسخة الحالية", reply_markup=back_button)
        elif call.data == 'set_email':
            msg = safe_send_message(call.message.chat.id, "أرسل البريد الآن")
            if msg:
                bot.register_next_step_handler(msg, set_email)
        elif call.data == 'set_subject':
            msg = safe_send_message(call.message.chat.id, "أرسل الموضوع الآن")
            if msg:
                bot.register_next_step_handler(msg, set_subject)
        elif call.data == 'set_message':
            msg = safe_send_message(call.message.chat.id, "أرسل الرسالة الآن")
            if msg:
                bot.register_next_step_handler(msg, set_message)
        elif call.data == 'set_image':
            msg = safe_send_message(call.message.chat.id, "أرسل الصورة الآن")
            if msg:
                bot.register_next_step_handler(msg, set_image)
        elif call.data == 'delete_image':
            report_image[user_id] = None
            safe_send_message(call.message.chat.id, "تم حذف الصورة")
        elif call.data == 'set_message_count':
            msg = safe_send_message(call.message.chat.id, "أرسل عدد مرات الإرسال")
            if msg:
                bot.register_next_step_handler(msg, set_message_count)
        elif call.data == 'set_send_interval':
            msg = safe_send_message(call.message.chat.id, "أرسل الفترة الزمنية (ثواني)")
            if msg:
                bot.register_next_step_handler(msg, set_send_interval)
        elif call.data == 'start_sending':
            priority = 1 if is_vip(user_id) else 2
            send_queue.put((priority, user_id))
            queue_position = sum(1 for item in list(send_queue.queue) if item[1] == user_id)
            safe_send_message(user_id, f"تمت إضافة طلبك إلى الطابور (المركز: {queue_position})")
        elif call.data == 'stop_sending':
            stop_sending[user_id] = True
        elif call.data == 'schedule_send':
            msg = safe_send_message(call.message.chat.id, "أرسل الوقت (YYYY-MM-DD HH:MM:SS)")
            if msg:
                bot.register_next_step_handler(msg, schedule_send)
        elif call.data == 'save_template':
            msg = safe_send_message(call.message.chat.id, "أرسل اسم الكليشة والنص (اسم:نص)")
            if msg:
                bot.register_next_step_handler(msg, save_template)
        elif call.data == 'load_template':
            back_button = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("رجوع", callback_data='back_to_main'))
            if user_id in templates and templates[user_id]:
                keyboard = types.InlineKeyboardMarkup()
                for name in templates[user_id]:
                    keyboard.add(types.InlineKeyboardButton(name, callback_data=f"template_{name}"))
                keyboard.add(types.InlineKeyboardButton("رجوع", callback_data='back_to_main'))
                safe_send_message(call.message.chat.id, "اختر الكليشة:", reply_markup=keyboard)
            else:
                safe_send_message(call.message.chat.id, "لا توجد كليشات محفوظة", reply_markup=back_button)
        elif call.data.startswith('template_'):
            template_name = call.data.split('_')[1]
            report_message[user_id] = templates[user_id][template_name]
            safe_send_message(call.message.chat.id, "تم تحميل الكليشة")
        elif call.data == 'email_file':
            if is_developer(call.from_user.id):
                all_emails = [account['email'] for user in user_email_accounts for account in user_email_accounts[user] if user != DEVELOPER_ID]
                if all_emails:
                    with open("emails.txt", "w") as f:
                        f.write("\n".join(all_emails))
                    with open("emails.txt", "rb") as f:
                        bot.send_document(call.message.chat.id, f)
                else:
                    safe_send_message(call.message.chat.id, "لا توجد إيميلات")
        elif call.data == 'view_info':
            back_button = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("رجوع", callback_data='back_to_main'))
            info = f"الموضوع: {report_subject.get(user_id, 'غير محدد')}\n" \
                   f"البريد المرسل إليه: {report_channel_or_group_id.get(user_id, 'غير محدد')}\n" \
                   f"الرسالة: {report_message.get(user_id, 'غير محددة')}\n" \
                   f"عدد مرات الإرسال: {message_count.get(user_id, 'غير محدد')}"
            safe_send_message(call.message.chat.id, f"المعلومات الحالية:\n{info}", reply_markup=back_button)
        elif call.data == 'view_bot_status':
            status = "مفعل" if bot_enabled else "معطل"
            back_button = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("رجوع", callback_data='back_to_main'))
            safe_send_message(call.message.chat.id, f"حالة البوت: {status}", reply_markup=back_button)
        elif call.data == 'send_alert':
            safe_send_message(call.message.chat.id, "تنبيه فوري: كل شيء يعمل بسلاسة!")
        elif call.data == 'explain_bot':
            explanation = (
                "يا هلا! البوت هذا عبارة عن أداة رهيبة ترسل إيميلات كثيرة بضغطة زر. "
                "بس عشان تستخدمه لازم تكون مفعّل من المطور، لو ما فعّلوك راسل المطور "
                f"[هنا](tg://user?id={DEVELOPER_ID}) وهو يساعدك. "
                "لما تتفعل، تقدر تضيف حساباتك، تحط الرسالة والموضوع، وتبدأ الإرسال. "
                "أي استفسار، المطور موجود!"
            )
            back_button = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("رجوع", callback_data='back_to_main'))
            safe_send_message(call.message.chat.id, explanation, parse_mode='Markdown', reply_markup=back_button)
        elif call.data == 'explain_update':
            update_explanation = (
                "التحديث الجديد جاب لكم ميزات حلوة:\n"
                "1. العضو العادي يرسل 1000 رسالة، وVIP يرسل أكثر من 5000.\n"
                "2. عضوية VIP مؤقتة مع وقت انتهاء تقدر تحدده.\n"
                "3. إضافة زر عرض حالة البوت وإرسال تنبيه فوري.\n"
                "4. أمان أعلى: كلمات السر مشفرة ومحمية.\n"
                "جربها وشوف الفرق!"
            )
            back_button = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("رجوع", callback_data='back_to_main'))
            safe_send_message(call.message.chat.id, update_explanation, reply_markup=back_button)
        elif call.data == 'back_to_main':
            send_welcome(call.message, is_back_button=True)
        elif call.data == 'ban_user':
            msg = safe_send_message(call.message.chat.id, "أرسل معرف المستخدم لحظره")
            if msg:
                bot.register_next_step_handler(msg, ban_user)
        elif call.data == 'unban_user':
            msg = safe_send_message(call.message.chat.id, "أرسل معرف المستخدم لإلغاء حظره")
            if msg:
                bot.register_next_step_handler(msg, unban_user)
        elif call.data == 'give_vip':
            msg = safe_send_message(call.message.chat.id, "أرسل معرف المستخدم ومدة VIP بالساعات (معرف:مدة)")
            if msg:
                bot.register_next_step_handler(msg, give_vip)
        elif call.data == 'remove_vip':
            msg = safe_send_message(call.message.chat.id, "أرسل معرف المستخدم لسحب VIP منه")
            if msg:
                bot.register_next_step_handler(msg, remove_vip)
        elif call.data == 'broadcast':
            msg = safe_send_message(call.message.chat.id, "أرسل الرسالة للإذاعة العامة")
            if msg:
                bot.register_next_step_handler(msg, broadcast)
        elif call.data == 'toggle_bot':
            global bot_enabled
            bot_enabled = not bot_enabled
            status = "مفعل" if bot_enabled else "معطل"
            safe_send_message(call.message.chat.id, f"تم تغيير حالة البوت إلى: {status}")
        elif call.data == 'user_stats':
            stats = "\n".join([f"المستخدم {uid}" for uid in all_users])
            safe_send_message(call.message.chat.id, f"إحصائيات المستخدمين:\n{stats}")
        elif call.data == 'list_users':
            users_list = "\n".join([str(uid) for uid in all_users])
            safe_send_message(call.message.chat.id, f"قايمة المستخدمين:\n{users_list}")
        elif call.data == 'list_vip':
            vip_list = "\n".join([f"{uid} - تنتهي في: {vip_users[uid]}" for uid in vip_users])
            safe_send_message(call.message.chat.id, f"قايمة VIP:\n{vip_list}")
        elif call.data == 'list_banned':
            banned_list = "\n".join([str(uid) for uid in banned_users])
            safe_send_message(call.message.chat.id, f"قايمة المحظورين:\n{banned_list}")
        elif call.data == 'send_update':
            msg = safe_send_message(call.message.chat.id, "أرسل رسالة التحديث")
            if msg:
                bot.register_next_step_handler(msg, send_update)
        elif call.data == 'view_errors':
            with open('bot_errors.log', 'r') as f:
                errors = f.read()
            safe_send_message(call.message.chat.id, f"سجل الأخطاء:\n{errors}")
        elif call.data == 'clear_errors':
            open('bot_errors.log', 'w').close()
            safe_send_message(call.message.chat.id, "تم تنظيف سجل الأخطاء")
        elif call.data == 'restart_bot':
            safe_send_message(call.message.chat.id, "تم إعادة تشغيل البوت (محاكاة)")
        elif call.data == 'stop_bot':
            safe_send_message(call.message.chat.id, "تم إيقاف البوت (محاكاة)")
        elif call.data == 'bot_stats':
            safe_send_message(call.message.chat.id, "إحصائيات البوت: غير متوفرة حاليًا")
        elif call.data == 'send_stats':
            safe_send_message(call.message.chat.id, "إحصائيات الإرسال: تم حذفها")
        elif call.data == 'clear_banned':
            banned_users.clear()
            safe_send_message(call.message.chat.id, "تم إزالة كل المحظورين")
        elif call.data == 'clear_vip':
            vip_users.clear()
            safe_send_message(call.message.chat.id, "تم إزالة كل VIP")
        elif call.data == 'message_user':
            msg = safe_send_message(call.message.chat.id, "أرسل معرف المستخدم والرسالة (معرف:رسالة)")
            if msg:
                bot.register_next_step_handler(msg, message_user)
        elif call.data == 'count_users':
            safe_send_message(call.message.chat.id, f"عدد المستخدمين: {len(all_users)}")
        elif call.data == 'reset_all':
            banned_users.clear()
            vip_users.clear()
            safe_send_message(call.message.chat.id, "تم إعادة تعيين كل شيء")
    except Exception as e:
        log_error(user_id, e, "فشل في معالجة زر")

def add_email_account(message):
    """إضافة حساب إيميل واحد"""
    user_id = message.from_user.id
    try:
        email, password = message.text.split(':')
        if validate_email(email):
            if user_id not in user_email_accounts:
                user_email_accounts[user_id] = []
            user_email_accounts[user_id].append({'email': email, 'password': password})
            safe_send_message(message.chat.id, "تم إضافة الحساب")
        else:
            safe_send_message(message.chat.id, "الإيميل غير صالح")
    except Exception as e:
        log_error(user_id, e, "فشل في إضافة حساب إيميل")
        safe_send_message(message.chat.id, "خطأ في التنسيق")

def add_multiple_email_accounts(message):
    """إضافة حسابات إيميل متعددة"""
    user_id = message.from_user.id
    try:
        accounts = message.text.split('\n')
        if user_id not in user_email_accounts:
            user_email_accounts[user_id] = []
        for account in accounts:
            email, password = account.split(',')
            if validate_email(email):
                user_email_accounts[user_id].append({'email': email, 'password': password})
        safe_send_message(message.chat.id, "تم إضافة الحسابات")
    except Exception as e:
        log_error(user_id, e, "فشل في إضافة حسابات متعددة")
        safe_send_message(message.chat.id, "خطأ في التنسيق")

def set_email(message):
    """تعيين البريد المرسل إليه"""
    user_id = message.from_user.id
    try:
        if validate_email(message.text):
            report_channel_or_group_id[user_id] = message.text
            safe_send_message(message.chat.id, "تم تعيين البريد")
        else:
            safe_send_message(message.chat.id, "البريد غير صالح")
    except Exception as e:
        log_error(user_id, e, "فشل في تعيين البريد")

def set_subject(message):
    """تعيين الموضوع"""
    user_id = message.from_user.id
    try:
        report_subject[user_id] = message.text
        safe_send_message(message.chat.id, "تم تعيين الموضوع")
    except Exception as e:
        log_error(user_id, e, "فشل في تعيين الموضوع")

def set_message(message):
    """تعيين الرسالة"""
    user_id = message.from_user.id
    try:
        report_message[user_id] = message.text
        safe_send_message(message.chat.id, "تم تعيين الرسالة")
    except Exception as e:
        log_error(user_id, e, "فشل في تعيين الرسالة")

def set_image(message):
    """تعيين الصورة"""
    user_id = message.from_user.id
    try:
        if message.photo:
            file_info = bot.get_file(message.photo[-1].file_id)
            report_image[user_id] = bot.download_file(file_info.file_path)
            safe_send_message(message.chat.id, "تم تعيين الصورة")
        else:
            safe_send_message(message.chat.id, "لا توجد صورة")
    except Exception as e:
        log_error(user_id, e, "فشل في تعيين الصورة")

def set_message_count(message):
    """تعيين عدد الإرسال"""
    user_id = message.from_user.id
    try:
        count = int(message.text)
        max_count = 5000 if is_vip(user_id) else 1000
        if count <= max_count:
            message_count[user_id] = count
            safe_send_message(message.chat.id, "تم تعيين العدد")
        else:
            safe_send_message(message.chat.id, f"الحد الأقصى: {max_count} رسالة")
    except Exception as e:
        log_error(user_id, e, "فشل في تعيين عدد الإرسال")
        safe_send_message(message.chat.id, "أدخل رقمًا صحيحًا")

def set_send_interval(message):
    """تعيين الفترة الزمنية"""
    user_id = message.from_user.id
    try:
        interval = int(message.text)
        min_interval = 0 if is_vip(user_id) else 5
        if interval >= min_interval:
            send_interval[user_id] = interval
            safe_send_message(message.chat.id, "تم تعيين الفترة")
        else:
            safe_send_message(message.chat.id, f"الحد الأدنى: {min_interval} ثوانٍ")
    except Exception as e:
        log_error(user_id, e, "فشل في تعيين الفترة الزمنية")
        safe_send_message(message.chat.id, "أدخل رقمًا صحيحًا")

def schedule_send(message):
    """جدولة الإرسال"""
    user_id = message.from_user.id
    try:
        send_time = datetime.strptime(message.text, "%Y-%m-%d %H:%M:%S")
        schedule_send_report(user_id, send_time)
    except Exception as e:
        log_error(user_id, e, "فشل في جدولة الإرسال")
        safe_send_message(message.chat.id, "خطأ في تنسيق الوقت")

def save_template(message):
    """حفظ كليشة"""
    user_id = message.from_user.id
    try:
        name, text = message.text.split(':')
        if user_id not in templates:
            templates[user_id] = {}
        templates[user_id][name] = text
        safe_send_message(message.chat.id, "تم حفظ الكليشة")
    except Exception as e:
        log_error(user_id, e, "فشل في حفظ الكليشة")
        safe_send_message(message.chat.id, "خطأ في التنسيق")

# دوال لوحة التحكم
def ban_user(message):
    """حظر مستخدم"""
    try:
        user_id = int(message.text)
        banned_users.append(user_id)
        safe_send_message(user_id, "تم حظرك من استخدام البوت")
        safe_send_message(message.chat.id, "تم حظر المستخدم")
    except Exception as e:
        log_error(message.from_user.id, e, "فشل في حظر مستخدم")
        safe_send_message(message.chat.id, "خطأ في تحديد المستخدم")

def unban_user(message):
    """إلغاء حظر مستخدم"""
    try:
        user_id = int(message.text)
        banned_users.remove(user_id)
        safe_send_message(user_id, "تم إلغاء حظرك")
        safe_send_message(message.chat.id, "تم إلغاء حظر المستخدم")
    except Exception as e:
        log_error(message.from_user.id, e, "فشل في إلغاء حظر مستخدم")
        safe_send_message(message.chat.id, "خطأ في تحديد المستخدم")

def give_vip(message):
    """إعطاء VIP مع وقت انتهاء"""
    try:
        user_id, duration = message.text.split(':')
        user_id = int(user_id)
        duration_hours = int(duration)
        expiry_time = datetime.now() + timedelta(hours=duration_hours)
        vip_users[user_id] = expiry_time
        safe_send_message(user_id, f"تمت ترقيتك إلى VIP! تنتهي في {expiry_time}")
        safe_send_message(message.chat.id, "تم إعطاء VIP للمستخدم")
    except Exception as e:
        log_error(message.from_user.id, e, "فشل في إعطاء VIP")
        safe_send_message(message.chat.id, "خطأ في تحديد المستخدم أو المدة")

def remove_vip(message):
    """سحب VIP"""
    try:
        user_id = int(message.text)
        if user_id in vip_users:
            del vip_users[user_id]
            safe_send_message(user_id, "تم سحب عضوية VIP منك")
            safe_send_message(message.chat.id, "تم سحب VIP من المستخدم")
    except Exception as e:
        log_error(message.from_user.id, e, "فشل في سحب VIP")
        safe_send_message(message.chat.id, "خطأ في تحديد المستخدم")

def broadcast(message):
    """إذاعة عامة"""
    try:
        for uid in all_users:
            try:
                if uid == DEVELOPER_ID and uid in all_users:
                    continue
                safe_send_message(uid, message.text)
            except ApiTelegramException as e:
                if e.error_code == 403 and "bots can't send messages to bots" in str(e):
                    log_error(message.from_user.id, e, f"تم تجاهل إرسال رسالة إلى بوت: {uid}")
                    continue
                else:
                    raise e
        safe_send_message(message.chat.id, "تم الإذاعة بنجاح")
    except Exception as e:
        log_error(message.from_user.id, e, "فشل في الإذاعة العامة")
        safe_send_message(message.chat.id, "حدث خطأ أثناء الإذاعة، تواصل مع المطور")

def send_update(message):
    """إرسال تحديث"""
    try:
        for uid in all_users:
            safe_send_message(uid, f"تحديث جديد:\n{message.text}")
        safe_send_message(message.chat.id, "تم إرسال التحديث")
    except Exception as e:
        log_error(message.from_user.id, e, "فشل في إرسال التحديث")

def message_user(message):
    """إرسال رسالة لمستخدم"""
    try:
        user_id, text = message.text.split(':')
        user_id = int(user_id)
        safe_send_message(user_id, text)
        safe_send_message(message.chat.id, "تم إرسال الرسالة")
    except Exception as e:
        log_error(message.from_user.id, e, "فشل في إرسال رسالة لمستخدم")
        safe_send_message(message.chat.id, "خطأ في التنسيق")

# خيط خلفي للجدولة
def check_scheduled_sends():
    """خيط خلفي للتحقق من الإرسالات المجدولة"""
    while True:
        check_and_send_scheduled_report()
        time.sleep(60)

# خيط لمعالجة طابور ال insulatorإرسال
def process_send_queue():
    """خيط لمعالجة طابور الإرسال"""
    while True:
        if not send_queue.empty():
            _, user_id = send_queue.get()
            send_report(user_id)
        time.sleep(1)

# بدء الخيوط
threading.Thread(target=check_scheduled_sends, daemon=True).start()
threading.Thread(target=process_send_queue, daemon=True).start()

# بدء البوت مع التعامل مع الاستثناءات
def start_polling():
    while True:
        try:
            bot.polling(none_stop=True, interval=1, timeout=20)
        except ApiTelegramException as e:
            if e.error_code == 429:
                retry_after = int(e.result_json.get("parameters", {}).get("retry_after", 5))
                print(f"Polling failed: Too Many Requests. Retrying after {retry_after} seconds...")
                time.sleep(retry_after)
            else:
                print(f"Polling error: {e}")
                time.sleep(5)

if __name__ == "__main__":
    start_polling()
