import json
import logging
import os
import sys
import threading
import time
from typing import Any, Dict, List, Optional
import uuid
import webbrowser

import wx
import wx.adv

from bot import Bot, app_vars
from bot.TeamTalk.structs import State
from bot.translator import Translator


_gui_translator: Optional[Translator] = None


def get_gui_translator(locale: Optional[str] = None) -> Translator:
    global _gui_translator
    if _gui_translator is None:
        _gui_translator = Translator(locale or "en")
    elif locale and _gui_translator.get_locale() != locale:
        try:
            _gui_translator.set_locale(locale)
        except Exception:
            pass
    return _gui_translator


def set_gui_locale(locale: str) -> None:
    t = get_gui_translator()
    try:
        t.set_locale(locale)
    except Exception as e:
        logging.error(f"Error setting GUI locale to {locale}: {e}")


def translate(message: str) -> str:
    """Translates a message using the active GUI translator."""
    return get_gui_translator().translate(message)


_cached_sound_devices: Optional[tuple[List[str], List[str]]] = None
_device_lock = threading.Lock()


def get_sound_device_choices() -> tuple[List[str], List[str]]:
    """Returns lists of formatted device strings for output and input sound devices."""
    global _cached_sound_devices
    with _device_lock:
        if _cached_sound_devices is not None:
            return _cached_sound_devices

        output_choices: List[str] = []
        input_choices: List[str] = []

        try:
            import mpv
            p = mpv.MPV()
            for i, dev in enumerate(p.audio_device_list):
                desc = dev.get("description") or dev.get("name") or "Unknown"
                output_choices.append(f"{i}: {desc}")
            p.terminate()
        except Exception as e:
            logging.error(f"Error querying mpv sound devices: {e}")

        try:
            import TeamTalkPy
            from bot.TeamTalk import _str
            tt = TeamTalkPy.TeamTalk()
            idx = 0
            for dev in tt.getSoundDevices():
                if sys.platform == "win32":
                    if dev.nSoundSystem == TeamTalkPy.SoundSystem.SOUNDSYSTEM_WASAPI and dev.nMaxInputChannels > 0:
                        name = _str(dev.szDeviceName)
                        input_choices.append(f"{idx}: {name}")
                        idx += 1
                else:
                    input_choices.append(f"{idx}: {_str(dev.szDeviceName)}")
                    idx += 1
            tt.closeTeamTalk()
        except Exception as e:
            logging.error(f"Error querying TeamTalk sound devices: {e}")

        if not output_choices:
            output_choices = ["0: Autoselect device"]
        if not input_choices:
            input_choices = ["0: Default Device"]

        _cached_sound_devices = (output_choices, input_choices)
        return _cached_sound_devices


SUPPORTED_LANGUAGES = [
    ("en", "English (en)"),
    ("ar", "Arabic (ar)"),
    ("es", "Spanish (es)"),
    ("hu", "Hungarian (hu)"),
    ("id", "Indonesian (id)"),
    ("pt_BR", "Portuguese (pt_BR)"),
    ("ru", "Russian (ru)"),
    ("tr", "Turkish (tr)"),
    ("vi", "Vietnamese (vi)"),
]

DEFAULT_SERVER_CONFIG: Dict[str, Any] = {
    "id": "",
    "name": "",
    "hostname": "",
    "tcp_port": 10333,
    "udp_port": 10333,
    "encrypted": False,
    "nickname": "TTMediaBot",
    "status": "",
    "gender": "n",
    "username": "",
    "password": "",
    "channel": "/",
    "channel_password": "",
    "license_name": "",
    "license_key": "",
    "reconnection_attempts": -1,
    "reconnection_timeout": 10,
    "admins": ["admin"],
    "banned_users": [],
    "load_event_handlers": False,
    "event_handlers_file_name": "event_handlers.py",
    "output_device": 2,
    "input_device": 0,
    "default_volume": 50,
    "max_volume": 100,
    "seek_step": 5,
    "volume_fading": True,
    "silence_trim": False,
    "default_service": "yt",
    "send_channel_messages": True,
    "search_results_mode": False,
    "video_subtitles": False,
    "start_commands": [],
    "cookiefile_path": "",
}


class ServerManager:
    """Manages the server list in servers.json and applies server configuration to config.json."""

    def __init__(self, config_path: str):
        self.config_path = os.path.abspath(config_path)
        # Store servers.json in user data directory (%APPDATA%\TTMediaBot)
        self.servers_file = os.path.join(app_vars.data_dir, "servers.json")
        self.servers: List[Dict[str, Any]] = []
        self.load_servers()

    def get_language(self) -> str:
        """Reads global language from config.json. Defaults to 'en'."""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data.get("general", {}).get("language", "en")
            except Exception as e:
                logging.error(f"Error reading language from {self.config_path}: {e}")
        return "en"

    def set_language(self, language: str) -> None:
        """Saves global language to config.json immediately."""
        data = {}
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                logging.error(f"Error reading {self.config_path}: {e}")
        if "general" not in data or not isinstance(data["general"], dict):
            data["general"] = {}
        data["general"]["language"] = language
        try:
            temp_file = self.config_path + ".tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_file, self.config_path)
            logging.info(f"Language '{language}' saved immediately to {self.config_path}")
        except Exception as e:
            logging.error(f"Error writing language to {self.config_path}: {e}")
            try:
                with open(self.config_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
            except Exception as ex:
                logging.error(f"Fallback save failed: {ex}")

    def load_servers(self) -> List[Dict[str, Any]]:
        """Loads servers from servers.json. By default, starts with an empty list."""
        old_servers_file = os.path.join(app_vars.directory, "servers.json")
        if not os.path.exists(self.servers_file) and os.path.exists(old_servers_file):
            try:
                import shutil
                shutil.copy2(old_servers_file, self.servers_file)
                logging.info(f"Migrated servers.json to {self.servers_file}")
            except Exception as e:
                logging.error(f"Error migrating servers.json: {e}")

        if os.path.exists(self.servers_file):
            try:
                with open(self.servers_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    for s in data:
                        if not s.get("id"):
                            s["id"] = str(uuid.uuid4())
                    self.servers = data
                    return self.servers
            except Exception as e:
                logging.error(f"Error reading {self.servers_file}: {e}")

        # Default is strictly an empty list (as requested by user)
        self.servers = []
        self.save_servers()
        return self.servers

    def save_servers(self) -> None:
        """Safely saves the server list to servers.json with atomic write."""
        try:
            temp_file = self.servers_file + ".tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self.servers, f, indent=4, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_file, self.servers_file)
        except Exception as e:
            logging.error(f"Error saving {self.servers_file}: {e}")
            try:
                with open(self.servers_file, "w", encoding="utf-8") as f:
                    json.dump(self.servers, f, indent=4, ensure_ascii=False)
            except Exception as ex:
                logging.error(f"Fallback save failed: {ex}")

    def add_server(self, server_data: Dict[str, Any]) -> int:
        if not server_data.get("id"):
            server_data["id"] = str(uuid.uuid4())
        self.servers.append(server_data)
        self.save_servers()
        return len(self.servers) - 1

    def update_server(self, index: int, server_data: Dict[str, Any]) -> None:
        if 0 <= index < len(self.servers):
            if not server_data.get("id"):
                server_data["id"] = self.servers[index].get("id") or str(uuid.uuid4())
            self.servers[index] = server_data
            self.save_servers()

    def delete_server(self, index: int) -> None:
        if 0 <= index < len(self.servers):
            del self.servers[index]
            self.save_servers()

    def apply_server_to_config(self, server: Dict[str, Any], config_path: str, language: Optional[str] = None) -> None:
        """Writes the selected server's settings to config.json before starting the bot."""
        data = {}
        template_file = self.config_path if os.path.exists(self.config_path) else config_path
        if os.path.exists(template_file):
            try:
                with open(template_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                logging.error(f"Error reading config template {template_file}: {e}")

        # 1. TeamTalk section
        if "teamtalk" not in data or not isinstance(data["teamtalk"], dict):
            data["teamtalk"] = {}
        tt = data["teamtalk"]
        tt["hostname"] = server.get("hostname", "localhost")
        tt["tcp_port"] = int(server.get("tcp_port", 10333))
        tt["udp_port"] = int(server.get("udp_port", 10333))
        tt["encrypted"] = bool(server.get("encrypted", False))
        tt["nickname"] = server.get("nickname", "TTMediaBot")
        tt["status"] = server.get("status", "")
        tt["gender"] = server.get("gender", "n")
        tt["username"] = server.get("username", "")
        tt["password"] = server.get("password", "")
        tt["channel"] = server.get("channel", "/")
        tt["channel_password"] = server.get("channel_password", "")
        tt["license_name"] = server.get("license_name", "")
        tt["license_key"] = server.get("license_key", "")
        tt["reconnection_attempts"] = int(server.get("reconnection_attempts", -1))
        tt["reconnection_timeout"] = int(server.get("reconnection_timeout", 10))

        if "users" not in tt or not isinstance(tt["users"], dict):
            tt["users"] = {}
        tt["users"]["admins"] = server.get("admins", ["admin"])
        tt["users"]["banned_users"] = server.get("banned_users", [])

        if "event_handling" not in tt or not isinstance(tt["event_handling"], dict):
            tt["event_handling"] = {}
        tt["event_handling"]["load_event_handlers"] = bool(server.get("load_event_handlers", False))
        tt["event_handling"]["event_handlers_file_name"] = server.get("event_handlers_file_name", "event_handlers.py")

        # 2. Sound devices section
        if "sound_devices" not in data or not isinstance(data["sound_devices"], dict):
            data["sound_devices"] = {}
        data["sound_devices"]["output_device"] = int(server.get("output_device", 2))
        data["sound_devices"]["input_device"] = int(server.get("input_device", 0))

        # 3. Player section
        if "player" not in data or not isinstance(data["player"], dict):
            data["player"] = {}
        pl = data["player"]
        pl["default_volume"] = int(server.get("default_volume", 50))
        pl["max_volume"] = int(server.get("max_volume", 100))
        pl["seek_step"] = int(server.get("seek_step", 5))
        pl["volume_fading"] = bool(server.get("volume_fading", True))
        pl["silence_trim"] = bool(server.get("silence_trim", False))

        # 4. General section
        if "general" not in data or not isinstance(data["general"], dict):
            data["general"] = {}
        gen = data["general"]
        gen["language"] = language or self.get_language()
        gen["send_channel_messages"] = bool(server.get("send_channel_messages", True))
        gen["search_results_mode"] = bool(server.get("search_results_mode", False))
        gen["video_subtitles"] = bool(server.get("video_subtitles", False))
        start_cmds = server.get("start_commands", [])
        if isinstance(start_cmds, str):
            start_cmds = [c.strip() for c in start_cmds.split(",") if c.strip()]
        gen["start_commands"] = start_cmds

        # 5. Services section
        if "services" not in data or not isinstance(data["services"], dict):
            data["services"] = {}
        svc = data["services"]
        svc["default_service"] = server.get("default_service", "yt")
        if "yt" not in svc or not isinstance(svc["yt"], dict):
            svc["yt"] = {}
        svc["yt"]["cookiefile_path"] = server.get("cookiefile_path", "")

        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)


class ServerDialog(wx.Dialog):
    """Dialog for adding or editing a TeamTalk server configuration."""

    def __init__(self, parent, title="Add Server", server_data: Optional[Dict[str, Any]] = None):
        super().__init__(
            parent,
            title=title,
            size=(580, 680),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.SetMinSize((500, 550))
        self.server_data = server_data or {}
        self.result_data: Optional[Dict[str, Any]] = None
        self._init_ui()
        self.CentreOnParent()

    def _init_ui(self):
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # Scrolled window containing all form fields
        scroll = wx.ScrolledWindow(self, style=wx.VSCROLL | wx.TAB_TRAVERSAL)
        scroll.SetScrollRate(0, 20)
        scroll_sizer = wx.BoxSizer(wx.VERTICAL)

        # ---------------- Section 1: Server Connection ----------------
        box_conn = wx.StaticBox(scroll, label=translate("Server Connection"))
        sizer_conn = wx.StaticBoxSizer(box_conn, wx.VERTICAL)

        # Server Display Name (Required)
        lbl_name = wx.StaticText(box_conn, label=translate("Server &Name (Required):"))
        self.txt_name = wx.TextCtrl(box_conn, value=self.server_data.get("name", ""))
        self.txt_name.SetToolTip(translate("Enter a display name for this server in the server list."))
        sizer_conn.Add(lbl_name, 0, wx.ALL, 3)
        sizer_conn.Add(self.txt_name, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        # Host / IP Address (Required)
        lbl_host = wx.StaticText(box_conn, label=translate("&Host / IP Address (Required):"))
        self.txt_hostname = wx.TextCtrl(box_conn, value=self.server_data.get("hostname", ""))
        self.txt_hostname.SetToolTip(translate("Enter the TeamTalk server hostname or IP address."))
        sizer_conn.Add(lbl_host, 0, wx.ALL, 3)
        sizer_conn.Add(self.txt_hostname, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        # Ports Row (TCP & UDP Ports - Required)
        ports_sizer = wx.BoxSizer(wx.HORIZONTAL)

        tcp_box = wx.BoxSizer(wx.VERTICAL)
        lbl_tcp = wx.StaticText(box_conn, label=translate("&TCP Port (Required):"))
        self.txt_tcp_port = wx.TextCtrl(box_conn, value=str(self.server_data.get("tcp_port", 10333)))
        tcp_box.Add(lbl_tcp, 0, wx.ALL, 3)
        tcp_box.Add(self.txt_tcp_port, 1, wx.EXPAND | wx.RIGHT, 5)
        ports_sizer.Add(tcp_box, 1, wx.EXPAND)

        udp_box = wx.BoxSizer(wx.VERTICAL)
        lbl_udp = wx.StaticText(box_conn, label=translate("&UDP Port (Required):"))
        self.txt_udp_port = wx.TextCtrl(box_conn, value=str(self.server_data.get("udp_port", 10333)))
        udp_box.Add(lbl_udp, 0, wx.ALL, 3)
        udp_box.Add(self.txt_udp_port, 1, wx.EXPAND | wx.LEFT, 5)
        ports_sizer.Add(udp_box, 1, wx.EXPAND)

        sizer_conn.Add(ports_sizer, 0, wx.EXPAND | wx.BOTTOM, 5)

        # Encrypted CheckBox
        self.chk_encrypted = wx.CheckBox(box_conn, label=translate("&Encrypted connection (SSL/TLS)"))
        self.chk_encrypted.SetValue(bool(self.server_data.get("encrypted", False)))
        sizer_conn.Add(self.chk_encrypted, 0, wx.ALL, 5)

        scroll_sizer.Add(sizer_conn, 0, wx.EXPAND | wx.ALL, 8)

        # ---------------- Section 2: Bot & Authentication ----------------
        box_auth = wx.StaticBox(scroll, label=translate("Bot & Authentication"))
        sizer_auth = wx.StaticBoxSizer(box_auth, wx.VERTICAL)

        # Bot Nickname (Required)
        lbl_nick = wx.StaticText(box_auth, label=translate("Bot &Nickname (Required):"))
        self.txt_nickname = wx.TextCtrl(box_auth, value=self.server_data.get("nickname", "TTMediaBot"))
        sizer_auth.Add(lbl_nick, 0, wx.ALL, 3)
        sizer_auth.Add(self.txt_nickname, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        # Gender Row (ComboBox)
        gender_box = wx.BoxSizer(wx.HORIZONTAL)
        lbl_gender = wx.StaticText(box_auth, label=translate("&Gender:"))
        gender_choices = [translate("None"), translate("Male"), translate("Female")]
        self.choice_gender = wx.Choice(box_auth, choices=gender_choices)
        gender_code = self.server_data.get("gender", "n").lower()
        sel_idx = 1 if gender_code == "m" else (2 if gender_code == "f" else 0)
        self.choice_gender.SetSelection(sel_idx)
        gender_box.Add(lbl_gender, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        gender_box.Add(self.choice_gender, 0, wx.EXPAND)
        sizer_auth.Add(gender_box, 0, wx.EXPAND | wx.ALL, 5)

        # Status Message (Optional)
        lbl_status = wx.StaticText(box_auth, label=translate("&Status Message (Optional):"))
        self.txt_status = wx.TextCtrl(box_auth, value=self.server_data.get("status", ""))
        sizer_auth.Add(lbl_status, 0, wx.ALL, 3)
        sizer_auth.Add(self.txt_status, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        # Username & Password Row (Optional)
        cred_sizer = wx.BoxSizer(wx.HORIZONTAL)

        user_box = wx.BoxSizer(wx.VERTICAL)
        lbl_user = wx.StaticText(box_auth, label=translate("&Username (Optional):"))
        self.txt_username = wx.TextCtrl(box_auth, value=self.server_data.get("username", ""))
        user_box.Add(lbl_user, 0, wx.ALL, 3)
        user_box.Add(self.txt_username, 1, wx.EXPAND | wx.RIGHT, 5)
        cred_sizer.Add(user_box, 1, wx.EXPAND)

        pass_box = wx.BoxSizer(wx.VERTICAL)
        lbl_pass = wx.StaticText(box_auth, label=translate("&Password (Optional):"))
        self.txt_password = wx.TextCtrl(box_auth, value=self.server_data.get("password", ""), style=wx.TE_PASSWORD)
        pass_box.Add(lbl_pass, 0, wx.ALL, 3)
        pass_box.Add(self.txt_password, 1, wx.EXPAND | wx.LEFT, 5)
        cred_sizer.Add(pass_box, 1, wx.EXPAND)

        sizer_auth.Add(cred_sizer, 0, wx.EXPAND | wx.BOTTOM, 5)

        # Default Channel & Channel Password Row (Optional)
        chan_sizer = wx.BoxSizer(wx.HORIZONTAL)

        chan_box = wx.BoxSizer(wx.VERTICAL)
        lbl_chan = wx.StaticText(box_auth, label=translate("Default &Channel (Optional, default /):"))
        self.txt_channel = wx.TextCtrl(box_auth, value=str(self.server_data.get("channel", "/")))
        chan_box.Add(lbl_chan, 0, wx.ALL, 3)
        chan_box.Add(self.txt_channel, 1, wx.EXPAND | wx.RIGHT, 5)
        chan_sizer.Add(chan_box, 1, wx.EXPAND)

        chan_pass_box = wx.BoxSizer(wx.VERTICAL)
        lbl_chan_pass = wx.StaticText(box_auth, label=translate("Channel Pass&word (Optional):"))
        self.txt_channel_password = wx.TextCtrl(
            box_auth, value=self.server_data.get("channel_password", ""), style=wx.TE_PASSWORD
        )
        chan_pass_box.Add(lbl_chan_pass, 0, wx.ALL, 3)
        chan_pass_box.Add(self.txt_channel_password, 1, wx.EXPAND | wx.LEFT, 5)
        chan_sizer.Add(chan_pass_box, 1, wx.EXPAND)

        sizer_auth.Add(chan_sizer, 0, wx.EXPAND | wx.BOTTOM, 5)

        scroll_sizer.Add(sizer_auth, 0, wx.EXPAND | wx.ALL, 8)

        # ---------------- Section 3: Sound Devices ----------------
        box_sound = wx.StaticBox(scroll, label=translate("Sound Devices"))
        sizer_sound = wx.StaticBoxSizer(box_sound, wx.VERTICAL)

        output_choices, input_choices = get_sound_device_choices()

        # Output Sound Device (Editable ComboBox)
        lbl_out = wx.StaticText(box_sound, label=translate("Output Sound &Device:"))
        self.combo_output_device = wx.ComboBox(
            box_sound,
            choices=output_choices,
            style=wx.CB_DROPDOWN,
        )
        self.combo_output_device.SetToolTip(translate("Select from the list or type the output sound device index or name."))
        self._set_combo_device_value(
            self.combo_output_device,
            output_choices,
            self.server_data.get("output_device", 2),
        )
        sizer_sound.Add(lbl_out, 0, wx.ALL, 3)
        sizer_sound.Add(self.combo_output_device, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        # Input Sound Device (Editable ComboBox)
        lbl_in = wx.StaticText(box_sound, label=translate("Input Sound De&vice:"))
        self.combo_input_device = wx.ComboBox(
            box_sound,
            choices=input_choices,
            style=wx.CB_DROPDOWN,
        )
        self.combo_input_device.SetToolTip(translate("Select from the list or type the input sound device index or name."))
        self._set_combo_device_value(
            self.combo_input_device,
            input_choices,
            self.server_data.get("input_device", 0),
        )
        sizer_sound.Add(lbl_in, 0, wx.ALL, 3)
        sizer_sound.Add(self.combo_input_device, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        scroll_sizer.Add(sizer_sound, 0, wx.EXPAND | wx.ALL, 8)

        # ---------------- Section 4: Audio & Playback ----------------
        box_playback = wx.StaticBox(scroll, label=translate("Audio & Playback"))
        sizer_playback = wx.StaticBoxSizer(box_playback, wx.VERTICAL)

        # Volume Row
        vol_sizer = wx.BoxSizer(wx.HORIZONTAL)

        def_vol_box = wx.BoxSizer(wx.VERTICAL)
        lbl_def_vol = wx.StaticText(box_playback, label=translate("Default &Volume (0-100, Required):"))
        self.txt_default_volume = wx.TextCtrl(
            box_playback, value=str(self.server_data.get("default_volume", 50))
        )
        self.txt_default_volume.SetToolTip(translate("Default playback volume percentage when bot starts playing."))
        def_vol_box.Add(lbl_def_vol, 0, wx.ALL, 3)
        def_vol_box.Add(self.txt_default_volume, 1, wx.EXPAND | wx.RIGHT, 5)
        vol_sizer.Add(def_vol_box, 1, wx.EXPAND)

        max_vol_box = wx.BoxSizer(wx.VERTICAL)
        lbl_max_vol = wx.StaticText(box_playback, label=translate("Max &Volume (0-100):"))
        self.txt_max_volume = wx.TextCtrl(
            box_playback, value=str(self.server_data.get("max_volume", 100))
        )
        self.txt_max_volume.SetToolTip(translate("Maximum allowed volume percentage users can set via commands."))
        max_vol_box.Add(lbl_max_vol, 0, wx.ALL, 3)
        max_vol_box.Add(self.txt_max_volume, 1, wx.EXPAND | wx.LEFT, 5)
        vol_sizer.Add(max_vol_box, 1, wx.EXPAND)

        sizer_playback.Add(vol_sizer, 0, wx.EXPAND | wx.BOTTOM, 5)

        # Seek Step Row
        lbl_seek = wx.StaticText(box_playback, label=translate("Seek Step in &Seconds:"))
        self.txt_seek_step = wx.TextCtrl(box_playback, value=str(self.server_data.get("seek_step", 5)))
        self.txt_seek_step.SetToolTip(translate("Number of seconds to jump when seeking forward or backward."))
        sizer_playback.Add(lbl_seek, 0, wx.ALL, 3)
        sizer_playback.Add(self.txt_seek_step, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        # Volume Fading & Silence Trim CheckBoxes
        self.chk_volume_fading = wx.CheckBox(box_playback, label=translate("Enable Volume &Fading (smooth track transitions)"))
        self.chk_volume_fading.SetValue(bool(self.server_data.get("volume_fading", True)))
        sizer_playback.Add(self.chk_volume_fading, 0, wx.ALL, 5)

        self.chk_silence_trim = wx.CheckBox(box_playback, label=translate("Enable &Silence Trim (remove silence at start/end)"))
        self.chk_silence_trim.SetValue(bool(self.server_data.get("silence_trim", False)))
        sizer_playback.Add(self.chk_silence_trim, 0, wx.ALL, 5)

        scroll_sizer.Add(sizer_playback, 0, wx.EXPAND | wx.ALL, 8)

        # ---------------- Section 5: Bot Behavior & Services ----------------
        box_behavior = wx.StaticBox(scroll, label=translate("Bot Behavior & Services"))
        sizer_behavior = wx.StaticBoxSizer(box_behavior, wx.VERTICAL)

        # Service Row
        srv_box = wx.BoxSizer(wx.VERTICAL)
        lbl_srv = wx.StaticText(box_behavior, label=translate("Default Music &Service:"))
        self.choice_service = wx.Choice(box_behavior, choices=["YouTube (yt)", "YouTube Music (ytm)"])
        self.choice_service.SetSelection(1 if self.server_data.get("default_service", "yt") == "ytm" else 0)
        srv_box.Add(lbl_srv, 0, wx.ALL, 3)
        srv_box.Add(self.choice_service, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)
        sizer_behavior.Add(srv_box, 0, wx.EXPAND | wx.BOTTOM, 5)

        # Checkboxes for Behavior
        self.chk_send_channel_messages = wx.CheckBox(box_behavior, label=translate("Send &Channel Messages (post notifications to channel)"))
        self.chk_send_channel_messages.SetValue(bool(self.server_data.get("send_channel_messages", True)))
        sizer_behavior.Add(self.chk_send_channel_messages, 0, wx.ALL, 5)

        self.chk_search_results_mode = wx.CheckBox(box_behavior, label=translate("Search &Results Mode (choose songs interactively 1-5)"))
        self.chk_search_results_mode.SetValue(bool(self.server_data.get("search_results_mode", False)))
        sizer_behavior.Add(self.chk_search_results_mode, 0, wx.ALL, 5)

        self.chk_video_subtitles = wx.CheckBox(box_behavior, label=translate("Display Video &Subtitles in status"))
        self.chk_video_subtitles.SetValue(bool(self.server_data.get("video_subtitles", False)))
        sizer_behavior.Add(self.chk_video_subtitles, 0, wx.ALL, 5)

        # Startup Commands
        lbl_start_cmds = wx.StaticText(box_behavior, label=translate("Startup Commands (Optional, comma-separated):"))
        start_cmds_raw = self.server_data.get("start_commands", [])
        if isinstance(start_cmds_raw, list):
            start_cmds_str = ", ".join(start_cmds_raw)
        else:
            start_cmds_str = str(start_cmds_raw)
        self.txt_start_commands = wx.TextCtrl(box_behavior, value=start_cmds_str)
        self.txt_start_commands.SetToolTip(translate("Commands executed automatically upon joining the server, e.g. 'v 60'"))
        sizer_behavior.Add(lbl_start_cmds, 0, wx.ALL, 3)
        sizer_behavior.Add(self.txt_start_commands, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        # YouTube Cookies File Path
        lbl_cookie = wx.StaticText(box_behavior, label=translate("YouTube Cookies File Path (Optional):"))
        self.txt_cookiefile = wx.TextCtrl(box_behavior, value=self.server_data.get("cookiefile_path", ""))
        self.txt_cookiefile.SetToolTip(translate("Path to cookies.txt file for YouTube authentication if needed."))
        sizer_behavior.Add(lbl_cookie, 0, wx.ALL, 3)
        sizer_behavior.Add(self.txt_cookiefile, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        scroll_sizer.Add(sizer_behavior, 0, wx.EXPAND | wx.ALL, 8)

        # ---------------- Section 6: Advanced Settings ----------------
        box_adv = wx.StaticBox(scroll, label=translate("Advanced Settings"))
        sizer_adv = wx.StaticBoxSizer(box_adv, wx.VERTICAL)

        # License Row (Optional)
        lic_sizer = wx.BoxSizer(wx.HORIZONTAL)

        lic_name_box = wx.BoxSizer(wx.VERTICAL)
        lbl_lic_name = wx.StaticText(box_adv, label=translate("License &Name (Optional):"))
        self.txt_license_name = wx.TextCtrl(box_adv, value=self.server_data.get("license_name", ""))
        lic_name_box.Add(lbl_lic_name, 0, wx.ALL, 3)
        lic_name_box.Add(self.txt_license_name, 1, wx.EXPAND | wx.RIGHT, 5)
        lic_sizer.Add(lic_name_box, 1, wx.EXPAND)

        lic_key_box = wx.BoxSizer(wx.VERTICAL)
        lbl_lic_key = wx.StaticText(box_adv, label=translate("License &Key (Optional):"))
        self.txt_license_key = wx.TextCtrl(box_adv, value=self.server_data.get("license_key", ""))
        lic_key_box.Add(lbl_lic_key, 0, wx.ALL, 3)
        lic_key_box.Add(self.txt_license_key, 1, wx.EXPAND | wx.LEFT, 5)
        lic_sizer.Add(lic_key_box, 1, wx.EXPAND)

        sizer_adv.Add(lic_sizer, 0, wx.EXPAND | wx.BOTTOM, 5)

        # Admins (Optional)
        lbl_admins = wx.StaticText(box_adv, label=translate("&Administrators (Optional, comma-separated usernames):"))
        existing_admins = self.server_data.get("admins", ["admin"])
        admins_str = ", ".join(existing_admins) if isinstance(existing_admins, list) else str(existing_admins)
        self.txt_admins = wx.TextCtrl(box_adv, value=admins_str or "admin")
        sizer_adv.Add(lbl_admins, 0, wx.ALL, 3)
        sizer_adv.Add(self.txt_admins, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        # Reconnection Attempts & Timeout (Optional)
        recon_sizer = wx.BoxSizer(wx.HORIZONTAL)

        att_box = wx.BoxSizer(wx.VERTICAL)
        lbl_recon_att = wx.StaticText(box_adv, label=translate("Reconnection &Attempts (-1 for infinite):"))
        self.txt_recon_attempts = wx.TextCtrl(
            box_adv, value=str(self.server_data.get("reconnection_attempts", -1))
        )
        att_box.Add(lbl_recon_att, 0, wx.ALL, 3)
        att_box.Add(self.txt_recon_attempts, 1, wx.EXPAND | wx.RIGHT, 5)
        recon_sizer.Add(att_box, 1, wx.EXPAND)

        tout_box = wx.BoxSizer(wx.VERTICAL)
        lbl_recon_tout = wx.StaticText(box_adv, label=translate("Reconnection &Timeout in seconds:"))
        self.txt_recon_timeout = wx.TextCtrl(
            box_adv, value=str(self.server_data.get("reconnection_timeout", 10))
        )
        tout_box.Add(lbl_recon_tout, 0, wx.ALL, 3)
        tout_box.Add(self.txt_recon_timeout, 1, wx.EXPAND | wx.LEFT, 5)
        recon_sizer.Add(tout_box, 1, wx.EXPAND)

        sizer_adv.Add(recon_sizer, 0, wx.EXPAND | wx.BOTTOM, 5)

        # Event Handlers CheckBox & File Name
        self.chk_load_event_handlers = wx.CheckBox(box_adv, label=translate("&Load Event Handlers"))
        self.chk_load_event_handlers.SetValue(bool(self.server_data.get("load_event_handlers", False)))
        sizer_adv.Add(self.chk_load_event_handlers, 0, wx.ALL, 5)

        lbl_eh_file = wx.StaticText(box_adv, label=translate("Event Handlers &File Name:"))
        self.txt_event_handlers_file = wx.TextCtrl(
            box_adv, value=self.server_data.get("event_handlers_file_name", "event_handlers.py")
        )
        sizer_adv.Add(lbl_eh_file, 0, wx.ALL, 3)
        sizer_adv.Add(self.txt_event_handlers_file, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5)

        scroll_sizer.Add(sizer_adv, 0, wx.EXPAND | wx.ALL, 8)

        scroll.SetSizer(scroll_sizer)
        main_sizer.Add(scroll, 1, wx.EXPAND)

        # ---------------- Dialog Buttons (OK / Cancel) ----------------
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_ok = wx.Button(self, wx.ID_OK, translate("&OK"))
        self.btn_cancel = wx.Button(self, wx.ID_CANCEL, translate("&Cancel"))
        self.btn_ok.SetDefault()

        self.btn_ok.Bind(wx.EVT_BUTTON, self.on_ok)
        self.btn_cancel.Bind(wx.EVT_BUTTON, self.on_cancel)

        btn_sizer.AddStretchSpacer()
        btn_sizer.Add(self.btn_ok, 0, wx.RIGHT, 10)
        btn_sizer.Add(self.btn_cancel, 0)
        main_sizer.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 10)

        self.SetSizer(main_sizer)

    def _set_combo_device_value(self, combo: wx.ComboBox, choices: List[str], target_index: Any):
        try:
            target_idx = int(target_index)
        except (ValueError, TypeError):
            target_idx = 0

        matched_str = None
        for ch in choices:
            if ch.startswith(f"{target_idx}:"):
                matched_str = ch
                break

        if matched_str:
            combo.SetValue(matched_str)
        else:
            combo.SetValue(str(target_idx))

    def _parse_device_index(self, combo: wx.ComboBox, default: int = 0) -> int:
        val = combo.GetValue().strip()
        if not val:
            sel = combo.GetSelection()
            return sel if sel != wx.NOT_FOUND else default

        # Formats like "2: Line 1 (Virtual Audio Cable)"
        if ":" in val:
            prefix = val.split(":", 1)[0].strip()
            if prefix.isdigit():
                return int(prefix)

        # Direct number like "2"
        if val.isdigit():
            return int(val)

        # Search matching choice text
        for idx in range(combo.GetCount()):
            item_text = combo.GetString(idx)
            if val.lower() in item_text.lower():
                if ":" in item_text:
                    prefix = item_text.split(":", 1)[0].strip()
                    if prefix.isdigit():
                        return int(prefix)
                return idx

        sel = combo.GetSelection()
        return sel if sel != wx.NOT_FOUND else default

    def on_ok(self, event):
        # Validate Required Fields
        name = self.txt_name.GetValue().strip()
        if not name:
            wx.MessageBox(translate("Please enter a server name."), translate("Validation Error"), wx.OK | wx.ICON_WARNING, self)
            self.txt_name.SetFocus()
            return

        hostname = self.txt_hostname.GetValue().strip()
        if not hostname:
            wx.MessageBox(translate("Please enter a host or IP address."), translate("Validation Error"), wx.OK | wx.ICON_WARNING, self)
            self.txt_hostname.SetFocus()
            return

        tcp_str = self.txt_tcp_port.GetValue().strip()
        try:
            tcp_port = int(tcp_str)
            if not (1 <= tcp_port <= 65535):
                raise ValueError()
        except ValueError:
            wx.MessageBox(translate("TCP Port must be an integer between 1 and 65535."), translate("Validation Error"), wx.OK | wx.ICON_WARNING, self)
            self.txt_tcp_port.SetFocus()
            return

        udp_str = self.txt_udp_port.GetValue().strip()
        try:
            udp_port = int(udp_str)
            if not (1 <= udp_port <= 65535):
                raise ValueError()
        except ValueError:
            wx.MessageBox(translate("UDP Port must be an integer between 1 and 65535."), translate("Validation Error"), wx.OK | wx.ICON_WARNING, self)
            self.txt_udp_port.SetFocus()
            return

        nickname = self.txt_nickname.GetValue().strip()
        if not nickname:
            wx.MessageBox(translate("Please enter a bot nickname."), translate("Validation Error"), wx.OK | wx.ICON_WARNING, self)
            self.txt_nickname.SetFocus()
            return

        # Volume validation
        vol_str = self.txt_default_volume.GetValue().strip()
        try:
            default_volume = int(vol_str)
            if not (0 <= default_volume <= 100):
                raise ValueError()
        except ValueError:
            wx.MessageBox(translate("Default volume must be an integer between 0 and 100."), translate("Validation Error"), wx.OK | wx.ICON_WARNING, self)
            self.txt_default_volume.SetFocus()
            return

        max_vol_str = self.txt_max_volume.GetValue().strip()
        try:
            max_volume = int(max_vol_str)
            if not (0 <= max_volume <= 100):
                raise ValueError()
        except ValueError:
            wx.MessageBox(translate("Max volume must be an integer between 0 and 100."), translate("Validation Error"), wx.OK | wx.ICON_WARNING, self)
            self.txt_max_volume.SetFocus()
            return

        if default_volume > max_volume:
            wx.MessageBox(translate("Default volume cannot be greater than max volume."), translate("Validation Error"), wx.OK | wx.ICON_WARNING, self)
            self.txt_default_volume.SetFocus()
            return

        seek_str = self.txt_seek_step.GetValue().strip()
        try:
            seek_step = int(seek_str) if seek_str else 5
            if seek_step < 1:
                raise ValueError()
        except ValueError:
            wx.MessageBox(translate("Seek step must be at least 1 second."), translate("Validation Error"), wx.OK | wx.ICON_WARNING, self)
            self.txt_seek_step.SetFocus()
            return

        recon_att_str = self.txt_recon_attempts.GetValue().strip()
        try:
            recon_attempts = int(recon_att_str) if recon_att_str else -1
        except ValueError:
            wx.MessageBox(translate("Reconnection attempts must be an integer (e.g. -1 for infinite)."), translate("Validation Error"), wx.OK | wx.ICON_WARNING, self)
            self.txt_recon_attempts.SetFocus()
            return

        recon_tout_str = self.txt_recon_timeout.GetValue().strip()
        try:
            recon_timeout = int(recon_tout_str) if recon_tout_str else 10
            if recon_timeout < 0:
                raise ValueError()
        except ValueError:
            wx.MessageBox(translate("Reconnection timeout must be a non-negative integer."), translate("Validation Error"), wx.OK | wx.ICON_WARNING, self)
            self.txt_recon_timeout.SetFocus()
            return

        admins_raw = self.txt_admins.GetValue().strip()
        admins = [a.strip() for a in admins_raw.split(",") if a.strip()]
        if not admins:
            admins = ["admin"]

        gender_map = {0: "n", 1: "m", 2: "f"}
        gender = gender_map.get(self.choice_gender.GetSelection(), "n")

        channel_val = self.txt_channel.GetValue().strip() or "/"
        if channel_val.isdigit():
            channel_val = int(channel_val)

        out_dev = self._parse_device_index(
            self.combo_output_device,
            default=int(self.server_data.get("output_device", 2)),
        )
        in_dev = self._parse_device_index(
            self.combo_input_device,
            default=int(self.server_data.get("input_device", 0)),
        )

        default_service = "ytm" if self.choice_service.GetSelection() == 1 else "yt"

        start_cmds_raw = self.txt_start_commands.GetValue().strip()
        start_commands = [c.strip() for c in start_cmds_raw.split(",") if c.strip()]

        self.result_data = {
            "name": name,
            "hostname": hostname,
            "tcp_port": tcp_port,
            "udp_port": udp_port,
            "encrypted": self.chk_encrypted.GetValue(),
            "nickname": nickname,
            "gender": gender,
            "status": self.txt_status.GetValue().strip(),
            "username": self.txt_username.GetValue().strip(),
            "password": self.txt_password.GetValue(),
            "channel": channel_val,
            "channel_password": self.txt_channel_password.GetValue(),
            "license_name": self.txt_license_name.GetValue().strip(),
            "license_key": self.txt_license_key.GetValue().strip(),
            "admins": admins,
            "banned_users": self.server_data.get("banned_users", []),
            "reconnection_attempts": recon_attempts,
            "reconnection_timeout": recon_timeout,
            "load_event_handlers": self.chk_load_event_handlers.GetValue(),
            "event_handlers_file_name": self.txt_event_handlers_file.GetValue().strip() or "event_handlers.py",
            "output_device": out_dev,
            "input_device": in_dev,
            "default_volume": default_volume,
            "max_volume": max_volume,
            "seek_step": seek_step,
            "volume_fading": self.chk_volume_fading.GetValue(),
            "silence_trim": self.chk_silence_trim.GetValue(),
            "default_service": default_service,
            "send_channel_messages": self.chk_send_channel_messages.GetValue(),
            "search_results_mode": self.chk_search_results_mode.GetValue(),
            "video_subtitles": self.chk_video_subtitles.GetValue(),
            "start_commands": start_commands,
            "cookiefile_path": self.txt_cookiefile.GetValue().strip(),
            "id": self.server_data.get("id") or str(uuid.uuid4()),
        }
        if self.IsModal():
            self.EndModal(wx.ID_OK)
        else:
            self.SetReturnCode(wx.ID_OK)
            self.Hide()

    def on_cancel(self, event):
        if self.IsModal():
            self.EndModal(wx.ID_CANCEL)
        else:
            self.SetReturnCode(wx.ID_CANCEL)
            self.Hide()


# Win32 Tray Hook Helpers for Windows 10
_win32_wndproc_hook_supported = False
if sys.platform == "win32":
    try:
        import ctypes
        from ctypes import wintypes

        _user32 = ctypes.windll.user32
        _GWLP_WNDPROC = -4

        if sys.maxsize > 2**32:
            _WNDPROC = ctypes.WINFUNCTYPE(
                ctypes.c_longlong, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
            )
            _SetWindowLongPtr = _user32.SetWindowLongPtrW
            _SetWindowLongPtr.restype = ctypes.c_void_p
            _SetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
            _CallWindowProc = _user32.CallWindowProcW
            _CallWindowProc.restype = ctypes.c_longlong
            _CallWindowProc.argtypes = [
                ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
            ]
        else:
            _WNDPROC = ctypes.WINFUNCTYPE(
                ctypes.c_long, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
            )
            _SetWindowLongPtr = getattr(_user32, "SetWindowLongPtrW", _user32.SetWindowLongW)
            _SetWindowLongPtr.restype = ctypes.c_void_p
            _SetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
            _CallWindowProc = _user32.CallWindowProcW
            _CallWindowProc.restype = ctypes.c_long
            _CallWindowProc.argtypes = [
                ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
            ]

        _msg_taskbar = _user32.RegisterWindowMessageW("wxTaskBarIconMessage")
        _win32_wndproc_hook_supported = True
    except Exception as e:
        logging.debug(f"Win32 tray hook initialization failed: {e}")


class BotTaskBarIcon(wx.adv.TaskBarIcon):
    """System tray icon allowing TTMediaBot to minimize to the background."""

    def __init__(self, frame: "MainFrame"):
        super().__init__()
        self.frame = frame
        self._helper_hwnd: Optional[int] = None
        self._old_wndproc: Optional[int] = None
        self._c_wndproc: Optional[Any] = None

        self._set_tray_icon()
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_DCLICK, self.on_restore)
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_UP, self.on_restore)
        self.Bind(wx.adv.EVT_TASKBAR_CLICK, self.on_restore)
        self.Bind(wx.adv.EVT_TASKBAR_BALLOON_CLICK, self.on_restore)

        self._install_win32_hook()

    def _install_win32_hook(self):
        """Hooks the internal taskbar window on Windows to handle keyboard activation (Enter/Space/Menu) on Windows 10."""
        if not _win32_wndproc_hook_supported:
            return
        try:
            for w in wx.GetTopLevelWindows():
                if isinstance(w, wx.Frame) and w != self.frame and w.GetTitle() == "" and w.GetParent() is None:
                    h = w.GetHandle()
                    if h:
                        self._helper_hwnd = h
                        break
            if not self._helper_hwnd:
                return

            def _wndproc(hwnd, msg, wparam, lparam):
                if msg == _msg_taskbar:
                    # 0x0400 = NIN_SELECT, 0x0401 = NIN_KEYSELECT (Enter or Space in Win10 notification area)
                    if lparam in (0x0400, 0x0401):
                        lparam = 0x0202  # WM_LBUTTONUP -> triggers wxEVT_TASKBAR_LEFT_UP -> on_restore
                    # 0x007B = WM_CONTEXTMENU (Apps key / Shift+F10 in Win10 notification area)
                    elif lparam == 0x007B:
                        lparam = 0x0205  # WM_RBUTTONUP -> triggers wxEVT_TASKBAR_RIGHT_UP -> CreatePopupMenu
                return _CallWindowProc(self._old_wndproc, hwnd, msg, wparam, lparam)

            self._c_wndproc = _WNDPROC(_wndproc)
            self._old_wndproc = _SetWindowLongPtr(
                self._helper_hwnd, _GWLP_WNDPROC, ctypes.cast(self._c_wndproc, ctypes.c_void_p)
            )
        except Exception as e:
            logging.debug(f"Failed to install Win32 taskbar hook: {e}")

    def _set_tray_icon(self):
        icon = wx.ArtProvider.GetIcon(wx.ART_INFORMATION, wx.ART_OTHER, (16, 16))
        self.SetIcon(icon, translate("TTMediaBot - Running in Background"))

    def CreatePopupMenu(self):
        menu = wx.Menu()
        item_show = menu.Append(wx.ID_ANY, translate("&Show Window"))
        menu.Bind(wx.EVT_MENU, self.on_restore, item_show)

        if len(self.frame.servers) >= 2:
            menu.AppendSeparator()
            has_active = any(
                state in ("connected", "connecting")
                for state in self.frame.server_states.values()
            )
            if has_active:
                item_toggle = menu.Append(wx.ID_ANY, translate("&Disconnect All Servers"))
                menu.Bind(wx.EVT_MENU, self.frame.on_disconnect_all, item_toggle)
            else:
                item_toggle = menu.Append(wx.ID_ANY, translate("&Connect All Servers"))
                menu.Bind(wx.EVT_MENU, self.frame.on_connect_all, item_toggle)

        menu.AppendSeparator()
        item_exit = menu.Append(wx.ID_ANY, translate("E&xit TTMediaBot"))
        menu.Bind(wx.EVT_MENU, self.on_exit, item_exit)
        return menu

    def on_restore(self, event=None):
        self.frame.show_from_tray()

    def on_exit(self, event=None):
        self.frame.Close()

    def Destroy(self):
        if self._helper_hwnd and self._old_wndproc and _win32_wndproc_hook_supported:
            try:
                _SetWindowLongPtr(self._helper_hwnd, _GWLP_WNDPROC, self._old_wndproc)
            except Exception:
                pass
            self._old_wndproc = None
            self._helper_hwnd = None
        return super().Destroy()


class MainFrame(wx.Frame):
    """Main window displaying the server list and connection controls."""

    def __init__(self, config_path: str, cache_path: Optional[str] = None, log_path: Optional[str] = None):
        super().__init__(None, title=translate("TTMediaBot - Server Manager"), size=(580, 580))
        self.SetMinSize((480, 460))
        self.config_path = config_path
        self.cache_path = cache_path
        self.log_path = log_path

        self.server_mgr = ServerManager(config_path)
        self.servers = self.server_mgr.servers
        self.visible_servers = list(self.servers)
        self.search_query = ""

        # Global language
        self.current_language = self.server_mgr.get_language()
        set_gui_locale(self.current_language)

        # Multi-server tracking
        self.active_bots: Dict[str, Bot] = {}
        self.bot_threads: Dict[str, threading.Thread] = {}
        self.server_states: Dict[str, str] = {}  # s_id -> "disconnected" | "connecting" | "connected" | "reconnecting"
        self._closing = False
        self.taskbar_icon: Optional[BotTaskBarIcon] = None
        self._current_status_text = "Disconnected"

        self._init_ui()
        self.retranslate_ui()
        self.CentreOnScreen()

        # Timer for polling connection states
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_timer, self.timer)
        self.timer.Start(500)

        # Pre-warm sound device querying in background so dialog opens instantly
        threading.Thread(target=get_sound_device_choices, daemon=True).start()

        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)

    def get_server_id(self, server: Dict[str, Any]) -> str:
        s_id = server.get("id")
        if not s_id:
            s_id = str(uuid.uuid4())
            server["id"] = s_id
        return s_id

    def on_char_hook(self, event):
        key = event.GetKeyCode()
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            focused = self.FindFocus()
            if focused == self.server_list or focused == self:
                self.on_connect_toggle(event)
                return
        event.Skip()

    def _init_ui(self):
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # Server List Label
        self.lbl_servers = wx.StaticText(panel, label="&Servers:")
        main_sizer.Add(self.lbl_servers, 0, wx.LEFT | wx.TOP | wx.RIGHT, 10)
        # Search Box
        search_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.lbl_search = wx.StaticText(panel, label=translate("&Search:"))
        self.txt_search = wx.SearchCtrl(panel, style=wx.TE_PROCESS_ENTER)
        self.txt_search.SetName(translate("Search"))
        self.txt_search.SetToolTip(translate("Type to search servers"))
        self.txt_search.SetDescriptiveText(translate("Search servers..."))
        self.txt_search.ShowSearchButton(True)
        self.txt_search.ShowCancelButton(True)
        self.txt_search.Bind(wx.EVT_TEXT, self.on_search)
        self.txt_search.Bind(wx.EVT_SEARCHCTRL_CANCEL_BTN, self.on_search_cancel)
        search_sizer.Add(self.lbl_search, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        search_sizer.Add(self.txt_search, 1, wx.EXPAND)
        main_sizer.Add(search_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

        # Server ListBox
        self.server_list = wx.ListBox(panel, style=wx.LB_SINGLE)
        self.server_list.Bind(wx.EVT_LISTBOX_DCLICK, self.on_connect_toggle)
        self.server_list.Bind(wx.EVT_KEY_DOWN, self.on_list_key_down)
        self.server_list.Bind(wx.EVT_CONTEXT_MENU, self.on_context_menu)
        main_sizer.Add(self.server_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

        # Language Selection Row
        lang_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.lbl_language = wx.StaticText(panel, label="&Language:")
        lang_labels = [label for _, label in SUPPORTED_LANGUAGES]
        self.choice_language = wx.Choice(panel, choices=lang_labels)
        self.choice_language.Bind(wx.EVT_CHOICE, self.on_language_changed)

        lang_idx = 0
        for i, (code, _) in enumerate(SUPPORTED_LANGUAGES):
            if code == self.current_language:
                lang_idx = i
                break
        self.choice_language.SetSelection(lang_idx)

        lang_sizer.Add(self.lbl_language, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        lang_sizer.Add(self.choice_language, 1, wx.EXPAND)
        main_sizer.Add(lang_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

        # Buttons Grid (3 rows x 2 columns)
        self.btn_sizer = wx.GridSizer(rows=4, cols=2, vgap=6, hgap=8)

        # Row 1: Connect All & Delete All
        self.btn_connect_all = wx.Button(panel, label="&Connect All")
        self.btn_connect_all.Show(len(self.servers) >= 2)
        self.btn_delete_all = wx.Button(panel, label="&Delete All Servers")
        self.btn_delete_all.Show(len(self.servers) >= 2)

        # Row 2: Add Server & Hide Window
        self.btn_add = wx.Button(panel, label="&Add Server...")

        # Row 2: Hide Window & Visit Website
        self.btn_hide = wx.Button(panel, label="&Hide Window")
        self.btn_website = wx.Button(panel, label="&Visit Website")

        # Row 3: Join Telegram Channel & Exit
        self.btn_telegram = wx.Button(panel, label="&Join Telegram Channel")
        self.btn_exit = wx.Button(panel, label="E&xit")

        self.btn_connect_all.Bind(wx.EVT_BUTTON, self.on_connect_all_toggle)
        self.btn_delete_all.Bind(wx.EVT_BUTTON, self.on_delete_all)
        self.btn_add.Bind(wx.EVT_BUTTON, self.on_add_server)
        self.btn_hide.Bind(wx.EVT_BUTTON, self.on_hide_window)
        self.btn_website.Bind(wx.EVT_BUTTON, self.on_visit_website)
        self.btn_telegram.Bind(wx.EVT_BUTTON, self.on_join_telegram)
        self.btn_exit.Bind(wx.EVT_BUTTON, self.on_exit)

        self.btn_sizer.Add(self.btn_connect_all, 1, wx.EXPAND)
        self.btn_sizer.Add(self.btn_delete_all, 1, wx.EXPAND)
        self.btn_sizer.Add(self.btn_add, 1, wx.EXPAND)
        self.btn_sizer.Add(self.btn_hide, 1, wx.EXPAND)
        self.btn_sizer.Add(self.btn_website, 1, wx.EXPAND)
        self.btn_sizer.Add(self.btn_telegram, 1, wx.EXPAND)
        self.btn_sizer.Add(self.btn_exit, 1, wx.EXPAND)

        main_sizer.Add(self.btn_sizer, 0, wx.EXPAND | wx.ALL, 10)

        # Status text label
        self.lbl_status = wx.StaticText(panel, label="Status: Disconnected")
        main_sizer.Add(self.lbl_status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        self.panel = panel
        self.panel.SetSizer(main_sizer)
        self.CreateStatusBar(1)

    def retranslate_ui(self):
        """Retranslates all UI strings to the active language."""
        self.SetTitle(translate("TTMediaBot - Server Manager"))
        self.lbl_servers.SetLabel(translate("&Servers:"))
        if hasattr(self, "lbl_search"):
            self.lbl_search.SetLabel(translate("&Search:"))
        if hasattr(self, "txt_search"):
            self.txt_search.SetDescriptiveText(translate("Search servers..."))
            self.txt_search.SetName(translate("Search"))
            self.txt_search.SetToolTip(translate("Type to search servers"))
        self.server_list.SetToolTip(
            translate("Select a server. Press Enter to connect/disconnect. Right-click or press Applications key for Context Menu.")
        )
        self.lbl_language.SetLabel(translate("&Language:"))
        for i, (code, _) in enumerate(SUPPORTED_LANGUAGES):
            if code == self.current_language:
                self.choice_language.SetSelection(i)
                break
        self.choice_language.SetToolTip(
            translate("Select the active language for the bot and interface.")
        )
        if hasattr(self, 'btn_delete_all'):
            self.btn_delete_all.SetLabel(translate("&Delete All Servers"))
            self.btn_delete_all.SetToolTip(translate("Delete all saved servers."))
        self.btn_add.SetLabel(translate("&Add Server..."))
        self.btn_add.SetToolTip(translate("Add a new server to the list."))
        self.btn_hide.SetLabel(translate("&Hide Window"))
        self.btn_hide.SetToolTip(translate("Minimize TTMediaBot window to the system tray."))
        self.btn_website.SetLabel(translate("&Visit Website"))
        self.btn_website.SetToolTip(translate("Open website: https://smartthinh.com/en/home"))
        self.btn_telegram.SetLabel(translate("&Join Telegram Channel"))
        self.btn_telegram.SetToolTip(translate("Open Telegram channel: https://t.me/accessiblevisionresources"))
        self.btn_exit.SetLabel(translate("E&xit"))
        self.btn_exit.SetToolTip(translate("Close TTMediaBot (or press Alt+F4)."))

        self.update_connect_all_button()
        self.update_status(self._current_status_text)
        self.SetStatusText(translate("Ready. Press Enter on a server to connect/disconnect. Right-click or Applications key for Context Menu."))
        self._populate_server_list()

        if self.taskbar_icon:
            self.taskbar_icon._set_tray_icon()

        self.panel.Layout()
        self.Layout()

    def on_language_changed(self, event=None):
        sel_idx = self.choice_language.GetSelection()
        if 0 <= sel_idx < len(SUPPORTED_LANGUAGES):
            new_lang = SUPPORTED_LANGUAGES[sel_idx][0]
            if new_lang != self.current_language:
                self.set_language(new_lang)

    def set_language(self, new_lang: str):
        self.current_language = new_lang
        set_gui_locale(new_lang)
        self.server_mgr.set_language(new_lang)

        # Update all active bots in real time
        for bot in self.active_bots.values():
            if hasattr(bot, "translator") and bot.translator:
                try:
                    bot.translator.set_locale(new_lang)
                except Exception as e:
                    logging.error(f"Error updating bot locale: {e}")
            if hasattr(bot, "subtitle_manager") and bot.subtitle_manager:
                bot.subtitle_manager.preferred_locale = new_lang

        # Retranslate GUI
        self.retranslate_ui()

    def on_search(self, event):
        self.search_query = self.txt_search.GetValue().strip().lower()
        self._populate_server_list()

    def on_search_cancel(self, event):
        self.txt_search.SetValue("")
        self.search_query = ""
        self._populate_server_list()

    def get_server_by_id(self, s_id: str) -> dict:
        for s in self.servers:
            if self.get_server_id(s) == s_id:
                return s
        return None

    def get_server_index_by_id(self, s_id: str) -> int:
        for idx, s in enumerate(self.servers):
            if self.get_server_id(s) == s_id:
                return idx
        return -1

    def _update_listbox_item(self, s_id: str):
        for idx, s in enumerate(self.visible_servers):
            if self.get_server_id(s) == s_id:
                name = s.get("name", translate("Unnamed Server"))
                state = self.server_states.get(s_id, "disconnected")
                if state == "connected":
                    name = f"[{translate('Connected')}] {name}"
                elif state == "connecting":
                    name = f"[{translate('Connecting')}] {name}"
                elif state == "reconnecting":
                    name = f"[{translate('Reconnecting')}] {name}"
                if idx < self.server_list.GetCount():
                    self.server_list.SetString(idx, name)
                break

    def _populate_server_list(self):
        curr_sel = self.server_list.GetSelection()
        selected_id = None
        if curr_sel != wx.NOT_FOUND and 0 <= curr_sel < len(self.visible_servers):
            selected_id = self.get_server_id(self.visible_servers[curr_sel])

        if self.search_query:
            self.visible_servers = [s for s in self.servers if self.search_query in s.get("name", "").lower()]
        else:
            self.visible_servers = list(self.servers)

        self.server_list.Clear()
        for idx, s in enumerate(self.visible_servers):
            name = s.get("name", translate("Unnamed Server"))
            s_id = self.get_server_id(s)
            state = self.server_states.get(s_id, "disconnected")
            if state == "connected":
                name = f"[{translate('Connected')}] {name}"
            elif state == "connecting":
                name = f"[{translate('Connecting')}] {name}"
            elif state == "reconnecting":
                name = f"[{translate('Reconnecting')}] {name}"
            self.server_list.Append(name)

        if len(self.visible_servers) > 0:
            if selected_id:
                found = False
                for i, s in enumerate(self.visible_servers):
                    if self.get_server_id(s) == selected_id:
                        self.server_list.SetSelection(i)
                        found = True
                        break
                if not found:
                    self.server_list.SetSelection(0)
            else:
                self.server_list.SetSelection(0)

        self.update_connect_all_button()

    def update_status(self, text: str):
        self._current_status_text = text
        self.lbl_status.SetLabel(f"{translate('Status')}: {text}")
        self.SetStatusText(text)

    def update_connect_all_button(self):
        show_btn = len(self.servers) >= 2
        if self.btn_connect_all.IsShown() != show_btn:
            self.btn_connect_all.Show(show_btn)
            if hasattr(self, 'btn_delete_all'):
                self.btn_delete_all.Show(show_btn)
            if hasattr(self, "btn_sizer"):
                self.btn_sizer.Layout()
            if hasattr(self, "panel"):
                self.panel.Layout()

        has_active = any(
            state in ("connected", "connecting")
            for state in self.server_states.values()
        )
        if has_active:
            self.btn_connect_all.SetLabel(translate("&Disconnect All"))
            self.btn_connect_all.SetToolTip(translate("Disconnect all connected TeamTalk servers."))
        else:
            self.btn_connect_all.SetLabel(translate("&Connect All"))
            self.btn_connect_all.SetToolTip(translate("Connect all configured servers to TeamTalk."))

    def on_list_key_down(self, event):
        key = event.GetKeyCode()
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self.on_connect_toggle(event)
        elif (key in (wx.WXK_WINDOWS_MENU, wx.WXK_MENU)) or (key == wx.WXK_F10 and event.ShiftDown()):
            self.show_context_menu(wx.DefaultPosition)
        elif key == wx.WXK_DELETE:
            self.on_delete_server(event)
        else:
            event.Skip()

    def on_context_menu(self, event):
        pos = event.GetPosition()
        self.show_context_menu(pos)

    def show_context_menu(self, screen_pos: wx.Point):
        client_pos = wx.DefaultPosition
        if screen_pos != wx.DefaultPosition and screen_pos != (-1, -1):
            client_pos = self.server_list.ScreenToClient(screen_pos)
            hit_idx = self.server_list.HitTest(client_pos)
            if hit_idx != wx.NOT_FOUND:
                self.server_list.SetSelection(hit_idx)

        sel = self.server_list.GetSelection()
        menu = wx.Menu()

        if sel != wx.NOT_FOUND and 0 <= sel < len(self.visible_servers):
            server = self.visible_servers[sel]
            s_id = self.get_server_id(server)
            server_name = server.get("name", translate("Server"))
            state = self.server_states.get(s_id, "disconnected")

            if state == "connected":
                item_conn = menu.Append(
                    wx.ID_ANY,
                    translate("&Disconnect from '{server_name}'").format(server_name=server_name),
                )
            elif state == "connecting":
                item_conn = menu.Append(
                    wx.ID_ANY,
                    translate("&Cancel Connecting to '{server_name}'").format(server_name=server_name),
                )
            else:
                item_conn = menu.Append(
                    wx.ID_ANY,
                    translate("&Connect to '{server_name}'").format(server_name=server_name),
                )
            self.Bind(wx.EVT_MENU, self.on_connect_toggle, item_conn)

            menu.AppendSeparator()

            item_edit = menu.Append(wx.ID_ANY, translate("&Edit Server..."))
            self.Bind(wx.EVT_MENU, self.on_edit_server, item_edit)
            if state in ("connected", "connecting"):
                item_edit.Enable(False)

            item_del = menu.Append(wx.ID_ANY, translate("&Delete Server"))
            self.Bind(wx.EVT_MENU, self.on_delete_server, item_del)
            if state in ("connected", "connecting"):
                item_del.Enable(False)

            menu.AppendSeparator()

        if len(self.servers) >= 2:
            has_active = any(st in ("connected", "connecting") for st in self.server_states.values())
            if has_active:
                item_all = menu.Append(wx.ID_ANY, translate("&Disconnect All Servers"))
                self.Bind(wx.EVT_MENU, self.on_disconnect_all, item_all)
            else:
                item_all = menu.Append(wx.ID_ANY, translate("&Connect All Servers"))
                self.Bind(wx.EVT_MENU, self.on_connect_all, item_all)
            menu.AppendSeparator()

        item_add = menu.Append(wx.ID_ANY, translate("&Add Server..."))
        self.Bind(wx.EVT_MENU, self.on_add_server, item_add)

        if client_pos != wx.DefaultPosition:
            self.server_list.PopupMenu(menu, client_pos)
        else:
            self.server_list.PopupMenu(menu)
        menu.Destroy()

    def on_connect_toggle(self, event=None):
        """Toggles connection for the selected server."""
        sel = self.server_list.GetSelection()
        if sel == wx.NOT_FOUND or sel < 0 or sel >= len(self.visible_servers):
            wx.MessageBox(
                translate("Please select a server from the list first."),
                translate("Information"),
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
            return

        server = self.visible_servers[sel]
        s_id = self.get_server_id(server)
        state = self.server_states.get(s_id, "disconnected")

        if state in ("connected", "connecting"):
            self.disconnect_single_server(self.visible_servers[sel])
        else:
            self.connect_single_server(self.visible_servers[sel])

    def on_connect_all_toggle(self, event=None):
        has_active = any(st in ("connected", "connecting") for st in self.server_states.values())
        if has_active:
            self.on_disconnect_all()
        else:
            self.on_connect_all()

    def on_connect_all(self, event=None):
        if not self.servers:
            wx.MessageBox(
                translate("No servers to connect. Please add a server first."),
                translate("Information"),
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
            return

        for idx, server in enumerate(self.servers):
            s_id = self.get_server_id(server)
            state = self.server_states.get(s_id, "disconnected")
            if state == "disconnected":
                self.connect_single_server(server)

        self.update_connect_all_button()
        self.update_status(translate("Connecting all servers..."))

    def on_disconnect_all(self, event=None):
        active_ids = [
            s_id for s_id, state in self.server_states.items()
            if state in ("connected", "connecting")
        ]
        if not active_ids:
            return

        for s_id in active_ids:
            self.disconnect_server_by_id(s_id)

        self.update_connect_all_button()
        self.update_status(translate("Disconnecting all servers..."))

    def connect_single_server(self, server: dict):
        if not server:
            return
        
        s_id = self.get_server_id(server)
        if self.server_states.get(s_id) in ("connected", "connecting"):
            return

        server_name = server.get("name", translate("Server"))
        self.server_states[s_id] = "connecting"
        
        self._update_listbox_item(s_id)

        self.update_connect_all_button()
        self.update_status(translate("Connecting to '{server_name}'...").format(server_name=server_name))

        cfg_path = os.path.join(app_vars.temp_dir, f".config_server_{idx}.json")
        cache_name = os.path.join(app_vars.cache_dir, f"TTMediaBotCache_{idx}.dat")
        log_name = os.path.join(app_vars.logs_dir, f"TTMediaBot_server_{idx}.log")

        thread = threading.Thread(
            target=self._bot_worker,
            args=(s_id, server, cfg_path, cache_name, log_name),
            daemon=True,
        )
        self.bot_threads[s_id] = thread
        thread.start()

    def _bot_worker(self, s_id: str, server: Dict[str, Any], cfg_path: str, cache_name: str, log_name: str):
        bot = None
        try:
            self.server_mgr.apply_server_to_config(server, cfg_path, language=self.current_language)
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg_data = json.load(f)
                cfg_data["general"]["cache_file_name"] = cache_name
                with open(cfg_path, "w", encoding="utf-8") as f:
                    json.dump(cfg_data, f, indent=4, ensure_ascii=False)
            except Exception as e:
                logging.error(f"Error updating server config cache file: {e}")

            bot = Bot(cfg_path, cache_file_name=cache_name, log_file_name=log_name)
            self.active_bots[s_id] = bot
            bot.initialize()
            bot.run()
        except Exception as e:
            logging.error(f"Error running bot for '{server.get('name')}': {e}", exc_info=True)
            wx.CallAfter(self.on_bot_error, server.get("name", translate("Server")), str(e))
        finally:
            if s_id in self.active_bots:
                del self.active_bots[s_id]
            wx.CallAfter(self.on_single_bot_stopped, s_id)
            try:
                if os.path.exists(cfg_path):
                    os.remove(cfg_path)
            except Exception:
                pass

    def disconnect_single_server(self, server: dict):
        if not server:
            return
        s_id = self.get_server_id(server)
        self.disconnect_server_by_id(s_id)

    def disconnect_server_by_id(self, s_id: str):
        bot_to_close = self.active_bots.get(s_id)
        if s_id in self.active_bots:
            del self.active_bots[s_id]

        self.server_states[s_id] = "disconnected"

        self._update_listbox_item(s_id)

        self.update_connect_all_button()

        if bot_to_close:
            def _close_worker():
                try:
                    bot_to_close.close()
                except Exception as e:
                    logging.error(f"Error during bot.close(): {e}")

            threading.Thread(target=_close_worker, daemon=True).start()

    def on_single_bot_stopped(self, s_id: str):
        if self._closing:
            return

        self.server_states[s_id] = "disconnected"
        self._update_listbox_item(s_id)

        self.update_connect_all_button()
        if not any(st in ("connected", "connecting") for st in self.server_states.values()):
            self.update_status(translate("Disconnected"))

    def on_bot_error(self, server_name: str, err_msg: str):
        if not self._closing:
            wx.MessageBox(
                translate("An error occurred while running the bot on '{server_name}':\n{err_msg}").format(
                    server_name=server_name, err_msg=err_msg
                ),
                translate("Connection Error"),
                wx.OK | wx.ICON_ERROR,
                self,
            )

    def on_timer(self, event):
        """Monitors all active bots' connection states and updates status."""
        if not self.active_bots:
            return

        status_parts = []
        any_changed = False

        for idx, server in enumerate(self.servers):
            s_id = self.get_server_id(server)
            bot = self.active_bots.get(s_id)
            if not bot:
                continue

            tt = getattr(bot, "ttclient", None)
            if not tt:
                continue

            prev_state = self.server_states.get(s_id, "disconnected")
            curr_state = prev_state

            if tt.state == State.CONNECTED:
                curr_state = "connected"
                ch = getattr(tt, "channel", None)
                ch_name = getattr(ch, "name", "/") if ch else "/"
                server_name = server.get("name", translate("Server"))
                status_parts.append(f"{server_name}: {translate('Connected')} ({ch_name})")
            elif tt.state == State.CONNECTING:
                curr_state = "connecting"
                server_name = server.get("name", translate("Server"))
                status_parts.append(f"{server_name}: {translate('Connecting')}")
            elif tt.state == State.RECONNECTING:
                curr_state = "reconnecting"
                attempt = getattr(tt, "reconnect_attempt", 0)
                server_name = server.get("name", translate("Server"))
                status_parts.append(f"{server_name}: {translate('Reconnecting')} ({attempt})")

            if hasattr(tt, "thread") and not tt.thread.is_alive() and prev_state in ("connected", "connecting"):
                curr_state = "disconnected"
                self.disconnect_server_by_id(s_id)

            if curr_state != prev_state:
                self.server_states[s_id] = curr_state
                any_changed = True
                if idx < self.server_list.GetCount():
                    s_name = server.get("name", translate("Unnamed Server"))
                    prefix = f"[{translate(curr_state.capitalize())}] " if curr_state != "disconnected" else ""
                    self.server_list.SetString(idx, f"{prefix}{s_name}")

        if any_changed:
            self.update_connect_all_button()

        if status_parts:
            self.update_status(" | ".join(status_parts))

    def hide_to_tray(self):
        """Hides the main window to the Windows system tray."""
        self.Hide()
        if not self.taskbar_icon:
            self.taskbar_icon = BotTaskBarIcon(self)
        try:
            self.taskbar_icon.ShowBalloon(
                translate("TTMediaBot"),
                translate("TTMediaBot is running in the background. Click the tray icon to restore."),
                2500,
            )
        except Exception:
            pass

    def show_from_tray(self):
        """Restores the main window from the system tray and ensures foreground activation."""
        if self.IsIconized():
            self.Iconize(False)
        self.Show(True)
        self.Restore()
        self.Raise()

        if sys.platform == "win32":
            try:
                import ctypes
                hwnd = self.GetHandle()
                if hwnd:
                    user32 = ctypes.windll.user32
                    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                    user32.SetForegroundWindow(hwnd)
            except Exception as e:
                logging.debug(f"Error setting foreground window: {e}")

        if hasattr(self, "server_list") and self.server_list:
            self.server_list.SetFocus()

    def on_hide_window(self, event=None):
        self.hide_to_tray()

    def on_add_server(self, event):
        dlg = ServerDialog(self, title=translate("Add New Server"))
        if dlg.ShowModal() == wx.ID_OK and dlg.result_data:
            new_idx = self.server_mgr.add_server(dlg.result_data)
            self.servers = self.server_mgr.servers
            self.search_query = ""
            if hasattr(self, 'txt_search'):
                self.txt_search.SetValue("")
            self._populate_server_list()
            self.server_list.SetSelection(self.server_list.GetCount() - 1)
            self.update_status(translate("Added server '{name}'").format(name=dlg.result_data['name']))
        dlg.Destroy()

    def on_edit_server(self, event):
        sel = self.server_list.GetSelection()
        if sel == wx.NOT_FOUND or sel < 0 or sel >= len(self.visible_servers):
            wx.MessageBox(
                translate("Please select a server to edit."),
                translate("Information"),
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
            return

        server = self.visible_servers[sel]
        s_id = self.get_server_id(server)
        orig_idx = self.get_server_index_by_id(s_id)
        if self.server_states.get(s_id) in ("connected", "connecting"):
            wx.MessageBox(
                translate("Cannot edit the server while the bot is connected to it. Please disconnect first."),
                translate("Notice"),
                wx.OK | wx.ICON_WARNING,
                self,
            )
            return

        dlg = ServerDialog(self, title=translate("Edit Server"), server_data=server)
        if dlg.ShowModal() == wx.ID_OK and dlg.result_data:
            dlg.result_data["id"] = s_id
            self.server_mgr.update_server(orig_idx, dlg.result_data)
            self.servers = self.server_mgr.servers
            self._populate_server_list()
            self.server_list.SetSelection(sel)
            self.update_status(translate("Updated server '{name}'").format(name=dlg.result_data['name']))
        dlg.Destroy()

    def on_delete_server(self, event):
        sel = self.server_list.GetSelection()
        if sel == wx.NOT_FOUND or sel < 0 or sel >= len(self.visible_servers):
            wx.MessageBox(
                translate("Please select a server to delete."),
                translate("Information"),
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
            return

        server = self.visible_servers[sel]
        s_id = self.get_server_id(server)
        orig_idx = self.get_server_index_by_id(s_id)
        s_id = self.get_server_id(server)
        if self.server_states.get(s_id) in ("connected", "connecting"):
            wx.MessageBox(
                translate("Cannot delete the server while the bot is connected to it. Please disconnect first."),
                translate("Notice"),
                wx.OK | wx.ICON_WARNING,
                self,
            )
            return

        server_name = server.get("name", translate("this server"))
        dlg = wx.MessageDialog(
            self,
            translate("Are you sure you want to delete server '{server_name}'?").format(server_name=server_name),
            translate("Confirm Delete"),
            wx.YES_NO | wx.ICON_QUESTION,
        )
        if dlg.ShowModal() == wx.ID_YES:
            self.server_mgr.delete_server(orig_idx)
            self.servers = self.server_mgr.servers
            self._populate_server_list()
            if len(self.visible_servers) > 0:
                new_sel = min(sel, len(self.visible_servers) - 1)
                self.server_list.SetSelection(new_sel)
            self.update_status(translate("Deleted server '{name}'").format(name=server_name))
        dlg.Destroy()

    def on_delete_all(self, event=None):
        if not self.servers:
            wx.MessageBox(
                translate("No servers to delete."),
                translate("Information"),
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
            return

        has_connected = any(st in ("connected", "connecting") for st in self.server_states.values())
        if has_connected:
            wx.MessageBox(
                translate("Some servers are currently connected. Please disconnect all servers before deleting."),
                translate("Notice"),
                wx.OK | wx.ICON_WARNING,
                self,
            )
            return

        dlg = wx.MessageDialog(
            self,
            translate("Are you sure you want to delete ALL servers? This action cannot be undone."),
            translate("Confirm Delete All"),
            wx.YES_NO | wx.ICON_WARNING,
        )
        if dlg.ShowModal() == wx.ID_YES:
            # Delete in reverse or simply clear
            self.server_mgr.servers.clear()
            self.server_mgr.save_servers()
            self.servers = self.server_mgr.servers
            self._populate_server_list()
            self.update_status(translate("All servers deleted."))
        dlg.Destroy()

    def on_visit_website(self, event=None):
        webbrowser.open("https://smartthinh.com/en/home")

    def on_join_telegram(self, event=None):
        webbrowser.open("https://t.me/accessiblevisionresources")

    def on_exit(self, event):
        self.Close()

    def on_close(self, event):
        """Handles window closing (including Alt+F4) and cleanly disconnects all bots."""
        self._closing = True
        self.timer.Stop()

        if self.taskbar_icon:
            try:
                self.taskbar_icon.RemoveIcon()
                self.taskbar_icon.Destroy()
            except Exception:
                pass
            self.taskbar_icon = None

        bots_to_close = list(self.active_bots.values())
        self.active_bots.clear()

        for b in bots_to_close:
            try:
                b.close()
            except Exception as e:
                logging.error(f"Error closing bot on exit: {e}")

        # Clean up any leftover temp config files in temp_dir
        try:
            for fname in os.listdir(app_vars.temp_dir):
                if fname.startswith(".config_server_") and fname.endswith(".json"):
                    try:
                        os.remove(os.path.join(app_vars.temp_dir, fname))
                    except Exception:
                        pass
        except Exception:
            pass

        self.Destroy()


def run_gui(config_path: str, cache_path: Optional[str] = None, log_path: Optional[str] = None):
    """Entry point for running the wx GUI."""
    app = wx.App(False)
    frame = MainFrame(config_path, cache_path, log_path)
    frame.Show()
    app.MainLoop()
