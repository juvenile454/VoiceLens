import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';
import {VIEW, ENTER_MS, RETURN_MS, FRAME_MS, placement, drawLens, labelOpacity} from './lens.js';
import * as IBusManager from 'resource:///org/gnome/shell/misc/ibusManager.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const Cairo = imports.cairo;

const APP_NAME = 'org.voicelens.VoiceLens';
const APP_PATH = '/org/voicelens/VoiceLens';
const HELPER_NAME = 'org.voicelens.VoiceLens.PttHelper';
const HELPER_PATH = '/org/voicelens/VoiceLens/PttHelper';
const POLL_MS = 40;
const PASTE_GUARD_MS = 180;
const HUD_FADE_MS = 180;
const HUD_WORK_MS = 960000;

const CHORD_MODS =
    Clutter.ModifierType.SHIFT_MASK |
    Clutter.ModifierType.MOD1_MASK |
    Clutter.ModifierType.SUPER_MASK |
    Clutter.ModifierType.META_MASK |
    Clutter.ModifierType.HYPER_MASK |
    Clutter.ModifierType.MOD4_MASK;
const IFACE = `<node>
  <interface name="org.voicelens.VoiceLens.PttHelper">
    <method name="Paste">
      <arg type="s" name="text" direction="in"/>
      <arg type="b" name="ok" direction="out"/>
    </method>
    <method name="PasteWithOptions">
      <arg type="s" name="text" direction="in"/>
      <arg type="b" name="terminal" direction="in"/>
      <arg type="b" name="ok" direction="out"/>
    </method>
    <method name="ShowStatus">
      <arg type="s" name="label" direction="in"/>
      <arg type="b" name="ok" direction="out"/>
    </method>
    <method name="ShowSession">
      <arg type="s" name="phase" direction="in"/>
      <arg type="s" name="label" direction="in"/>
      <arg type="i" name="x" direction="in"/>
      <arg type="i" name="y" direction="in"/>
      <arg type="i" name="height" direction="in"/>
      <arg type="b" name="caret" direction="in"/>
      <arg type="b" name="ok" direction="out"/>
    </method>
    <method name="FinishSession">
      <arg type="b" name="ok" direction="out"/>
    </method>
    <method name="HideStatus">
      <arg type="b" name="ok" direction="out"/>
    </method>
    <method name="SetLevel">
      <arg type="d" name="level" direction="in"/>
      <arg type="b" name="ok" direction="out"/>
    </method>
  </interface>
</node>`;

function isControl(keyval) {
    return keyval === Clutter.KEY_Control_L || keyval === Clutter.KEY_Control_R;
}

function isModifier(keyval) {
    return isControl(keyval) ||
        keyval === Clutter.KEY_Shift_L ||
        keyval === Clutter.KEY_Shift_R ||
        keyval === Clutter.KEY_Alt_L ||
        keyval === Clutter.KEY_Alt_R ||
        keyval === Clutter.KEY_Meta_L ||
        keyval === Clutter.KEY_Meta_R ||
        keyval === Clutter.KEY_Super_L ||
        keyval === Clutter.KEY_Super_R ||
        keyval === Clutter.KEY_Hyper_L ||
        keyval === Clutter.KEY_Hyper_R ||
        keyval === Clutter.KEY_Caps_Lock ||
        keyval === Clutter.KEY_Num_Lock ||
        keyval === Clutter.KEY_Scroll_Lock ||
        keyval === Clutter.KEY_ISO_Level3_Shift ||
        keyval === Clutter.KEY_ISO_Level5_Shift;
}

function isRepeated(event) {
    try {
        return Boolean(event.get_flags() & Clutter.EventFlags.FLAG_REPEATED);
    } catch (e) {
        return false;
    }
}

// Match application identifiers, never window titles or shell commands.
const TERMINAL_IDS = new Set([
    'gnome-terminal', 'gnome-terminal-server', 'org.gnome.terminal',
    'kgx', 'org.gnome.console', 'konsole', 'org.kde.konsole',
    'xfce4-terminal', 'tilix', 'com.gexperts.tilix', 'terminator',
    'kitty', 'alacritty', 'foot', 'footclient', 'wezterm', 'org.wezfurlong.wezterm',
    'ghostty', 'com.mitchellh.ghostty', 'blackbox', 'com.raggesilver.blackbox',
]);

function isTerminalWindow(win) {
    for (const method of ['get_gtk_application_id', 'get_wm_class', 'get_wm_class_instance']) {
        try {
            if (TERMINAL_IDS.has(String(win?.[method]?.() || '').toLowerCase()))
                return true;
        } catch (e) {
            // Not all client types expose each identifier.
        }
    }
    return false;
}

export default class VoiceLensPttExtension extends Extension {
    enable() {
        this._ctrlHeld = false;
        this._pasteGuard = false;
        this._pollId = 0;
        this._pasteGuardId = 0;
        this._hudTimeoutId = 0;
        this._hudPersist = false;
        this._phase = 'idle';
        this._level = 0;
        this._energy = 0;
        this._animId = 0;
        this._lastT = 0;
        this._finishInvocation = null;
        this._pasteId = 0;
        this._nativeCaret = null;
        this._nativeWindow = null;
        this._nativeFocus = null;
        this._ibusCaret = this._ibusWindow = null;
        this._sessionWindow = null;
        this._sessionCaret = null;
        this._interfaceSettings = new Gio.Settings({schema_id: 'org.gnome.desktop.interface'});
        this._cursorId = Main.inputMethod.connect('cursor-location-changed', (_method, rect) => {
            this._nativeCaret = {x: rect.get_x(), y: rect.get_y(), height: rect.get_height()};
            this._nativeWindow = global.display.focus_window;
            this._nativeFocus = Main.inputMethod.currentFocus;
            this._refreshCaret();
        });
        // Electron/XWayland clients can use IBus directly, bypassing
        // Main.inputMethod.currentFocus and the Wayland cursor signal.
        // Subscribe only to geometry/focus; never surrounding text or keys.
        this._ibusManager = IBusManager.getIBusManager();
        this._ibusIds = [
            this._ibusManager.connect('set-cursor-location', (_manager, rect) => this._setIBusCaret(rect)),
            this._ibusManager.connect('focus-in', () => this._clearIBusCaret()),
            this._ibusManager.connect('focus-out', () => this._clearIBusCaret()),
            this._ibusManager.connect('ready', () => {
                this._clearIBusCaret();
                this._connectRelativeCursor();
            }),
        ];
        this._relativePanel = null;
        this._relativeCursorId = 0;
        this._connectRelativeCursor();
        this._focusId = global.display.connect('notify::focus-window', () => {
            this._nativeCaret = null;
            this._nativeWindow = null;
            this._nativeFocus = null;
            this._clearIBusCaret();
            if (this._hudIsShowing() && global.display.focus_window !== this._sessionWindow) {
                this._hideHud();
                this._call('ptt-cancel');
            }
        });
        this._impl = Gio.DBusExportedObject.wrapJSObject(IFACE, this);
        this._impl.export(Gio.DBus.session, HELPER_PATH);
        this._nameId = Gio.bus_own_name(
            Gio.BusType.SESSION,
            HELPER_NAME,
            Gio.BusNameOwnerFlags.REPLACE,
            null,
            null,
            null
        );
        // Wayland does not deliver client-focused keys through captured-event.
        // Modifier bits from global.get_pointer() come from the compositor seat.
        this._eventId = global.stage.connect('captured-event', this._onEvent.bind(this));
        this._pollId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, POLL_MS, this._poll.bind(this));
    }

    disable() {
        if (this._pollId) {
            GLib.source_remove(this._pollId);
            this._pollId = 0;
        }
        if (this._pasteGuardId) {
            GLib.source_remove(this._pasteGuardId);
            this._pasteGuardId = 0;
        }
        if (this._pasteId) {
            GLib.source_remove(this._pasteId);
            this._pasteId = 0;
        }
        if (this._cursorId) Main.inputMethod.disconnect(this._cursorId);
        if (this._focusId) global.display.disconnect(this._focusId);
        this._disconnectRelativeCursor();
        for (const source of this._ibusIds || []) this._ibusManager.disconnect(source);
        this._ibusIds = [];
        this._ibusManager = null;
        this._clearIBusCaret();
        this._nativeCaret = this._nativeWindow = this._nativeFocus = null;
        this._sessionCaret = this._sessionWindow = null;
        this._cursorId = this._focusId = 0;
        this._interfaceSettings = null;
        this._destroyHud();
        if (this._eventId) {
            global.stage.disconnect(this._eventId);
            this._eventId = 0;
        }
        if (this._impl) {
            this._impl.unexport();
            this._impl = null;
        }
        if (this._nameId) {
            Gio.bus_unown_name(this._nameId);
            this._nameId = 0;
        }
        this._ctrlHeld = false;
        this._pasteGuard = false;
        this._hudPersist = false;
        this._phase = 'idle';
        this._level = 0;
        this._energy = 0;
    }

    Paste(text) {
        return this.PasteWithOptions(text, false);
    }

    PasteWithOptions(text, terminal) {
        try {
            if (!text || Main.sessionMode.isLocked || !this._sessionWindow ||
                global.display.focus_window !== this._sessionWindow || this._pasteId)
                return false;
            const targetWindow = this._sessionWindow;
            const terminalPaste = terminal || isTerminalWindow(targetWindow);
            this._beginPasteGuard();
            if (text)
                St.Clipboard.get_default().set_text(St.ClipboardType.CLIPBOARD, text);
            this._pasteId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 80, () => {
                this._pasteId = 0;
                try {
                    if (!Main.sessionMode.isLocked && global.display.focus_window === targetWindow)
                        this._pasteKey(terminalPaste);
                } finally {
                    this._beginPasteGuard();
                }
                return GLib.SOURCE_REMOVE;
            });
            return true;
        } catch (e) {
            this._endPasteGuard();
            log(`VoiceLens PTT paste failed: ${e}`);
            return false;
        }
    }

    ShowStatus(label) {
        try {
            if (Main.sessionMode.isLocked)
                return false;
            this._showHud(label || 'VoiceLens', this._ctrlHeld ? 'listening' : 'transcribing');
            return true;
        } catch (e) {
            log(`VoiceLens PTT status failed: ${e}`);
            return false;
        }
    }

    ShowSession(phase, label, x, y, height, caret) {
        if (Main.sessionMode.isLocked || !['listening', 'transcribing'].includes(phase))
            return false;
        try {
            this._showHud(label, phase, caret ? {x, y, height} : null);
            return true;
        } catch (e) {
            log(`VoiceLens session failed: ${e}`);
            this._hideHud();
            return false;
        }
    }

    FinishSessionAsync(_params, invocation) {
        this._resolveFinish(false);
        if (Main.sessionMode.isLocked || this._sessionWindow !== global.display.focus_window) {
            invocation.return_value(new GLib.Variant('(b)', [false]));
            return;
        }
        if (!this._hudIsShowing()) {
            invocation.return_value(new GLib.Variant('(b)', [true]));
            return;
        }
        this._finishInvocation = invocation;
        this._phase = 'returning';
        this._phaseT0 = GLib.get_monotonic_time() / 1000;
        this._label.hide();
        this._clearHudTimeout();
        // Also completes on a stopped frame clock (e.g. monitor turned off).
        this._hudTimeoutId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, RETURN_MS + 80, () => {
            this._hudTimeoutId = 0;
            this._completeReturn();
            return GLib.SOURCE_REMOVE;
        });
    }

    _resolveFinish(ok) {
        if (this._finishInvocation) {
            const invocation = this._finishInvocation;
            this._finishInvocation = null;
            invocation.return_value(new GLib.Variant('(b)', [ok]));
        }
    }

    _completeReturn() {
        this._resolveFinish(this._sessionWindow === global.display.focus_window && !Main.sessionMode.isLocked);
        this._hideHud(true);
    }

    HideStatus() {
        try {
            this._hideHud();
            return true;
        } catch (e) {
            log(`VoiceLens PTT hide failed: ${e}`);
            return false;
        }
    }

    SetLevel(level) {
        try {
            const value = Number(level);
            if (!this._hudPersist || !Number.isFinite(value))
                return true;
            this._level = Math.max(0, Math.min(1, value));
            return true;
        } catch (e) {
            return false;
        }
    }

    _beginPasteGuard() {
        this._pasteGuard = true;
        if (this._pasteGuardId) {
            GLib.source_remove(this._pasteGuardId);
            this._pasteGuardId = 0;
        }
        this._pasteGuardId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, PASTE_GUARD_MS, () => {
            this._pasteGuardId = 0;
            this._endPasteGuard();
            return GLib.SOURCE_REMOVE;
        });
    }

    _endPasteGuard() {
        this._pasteGuard = false;
        this._syncCtrlFromPointer();
    }

    _pasteKey(terminal = false) {
        const seat = Clutter.get_default_backend().get_default_seat();
        const virtualKeyboard = seat.create_virtual_device(Clutter.InputDeviceType.KEYBOARD_DEVICE);
        const time = global.get_current_time();
        virtualKeyboard.notify_keyval(time, Clutter.KEY_Control_L, Clutter.KeyState.PRESSED);
        if (terminal)
            virtualKeyboard.notify_keyval(time, Clutter.KEY_Shift_L, Clutter.KeyState.PRESSED);
        virtualKeyboard.notify_keyval(time, Clutter.KEY_v, Clutter.KeyState.PRESSED);
        virtualKeyboard.notify_keyval(time, Clutter.KEY_v, Clutter.KeyState.RELEASED);
        if (terminal)
            virtualKeyboard.notify_keyval(time, Clutter.KEY_Shift_L, Clutter.KeyState.RELEASED);
        virtualKeyboard.notify_keyval(time, Clutter.KEY_Control_L, Clutter.KeyState.RELEASED);
    }

    _poll() {
        this._syncCtrlFromPointer();
        return GLib.SOURCE_CONTINUE;
    }

    _pointerMods() {
        try {
            const result = global.get_pointer();
            if (!result || result.length < 3)
                return null;
            const mods = result[2];
            return typeof mods === 'number' ? mods : null;
        } catch (e) {
            return null;
        }
    }

    _syncCtrlFromPointer() {
        if (this._pasteGuard)
            return;
        try {
            if (Main.sessionMode.isLocked) {
                if (this._hudIsShowing()) {
                    this._hideHud(true);
                    this._call('ptt-cancel');
                }
                this._setCtrl(false);
                return;
            }
            const mods = this._pointerMods();
            if (mods === null)
                return;
            const ctrl = (mods & Clutter.ModifierType.CONTROL_MASK) !== 0;
            this._setCtrl(ctrl);
            if (ctrl && (mods & CHORD_MODS))
                this._chord();
        } catch (e) {
            log(`VoiceLens PTT poll failed: ${e}`);
        }
    }

    _setCtrl(pressed) {
        if (pressed === this._ctrlHeld)
            return;
        this._ctrlHeld = pressed;
        if (!pressed && this._phase === 'listening')
            this._enterTranscribing();
        this._call(pressed ? 'ptt-down' : 'ptt-up');
    }

    _chord() {
        if (this._ctrlHeld && !this._pasteGuard) {
            this._hideHud();
            this._call('ptt-chord');
        }
    }

    _enterTranscribing() {
        // Do not leave the listening caption up between release and the
        // application's localized transcribing message.
        if (this._phase === 'listening') this._label?.hide();
        this._hudPersist = false;
        this._phase = 'transcribing';
        this._level = 0;
        this._clearHudTimeout();
        this._hudTimeoutId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, HUD_WORK_MS, () => {
            this._hudTimeoutId = 0;
            this._hideHud();
            return GLib.SOURCE_REMOVE;
        });
    }

    _ensureHud() {
        if (this._hudBin) return;
        this._hudBin = new St.Widget({reactive: false, can_focus: false,
            width: VIEW, height: VIEW, style_class: 'voicelens-orb-bin'});
        this._core = new St.DrawingArea({reactive: false, can_focus: false,
            width: VIEW, height: VIEW, style_class: 'voicelens-orb-core'});
        this._repaintId = this._core.connect('repaint', this._paintOrb.bind(this));
        this._label = new St.Label({reactive: false, can_focus: false,
            style_class: 'voicelens-phase-label'});
        this._hudBin.add_child(this._core);
        this._hudBin.add_child(this._label);
        // Shell chrome, with no input region: never steals focus or a click.
        Main.layoutManager.addChrome(this._hudBin, {affectsInputRegion: false, trackFullscreen: true});
        this._hudBin.hide();
    }

    _disconnectRelativeCursor() {
        if (this._relativeCursorId) {
            try { this._relativePanel.disconnect(this._relativeCursorId); } catch (e) { /* IBus restarted */ }
        }
        this._relativePanel = null;
        this._relativeCursorId = 0;
    }

    _connectRelativeCursor() {
        this._disconnectRelativeCursor();
        // GNOME's manager forwards absolute rectangles publicly. Relative
        // ones are exposed by its panel service (same conversion as GNOME's
        // candidate popup). Keep this optional for older Shell/IBus versions.
        const panel = this._ibusManager?._panelService;
        if (!panel) return;
        try {
            this._relativeCursorId = panel.connect('set-cursor-location-relative', (_panel, x, y, width, height) => {
                const actor = global.display.focus_window?.get_compositor_private();
                if (actor) this._setIBusCaret({x: actor.x + x, y: actor.y + y, height});
            });
            this._relativePanel = panel;
        } catch (e) { /* Optional on older IBus */ }
    }

    _clearIBusCaret() {
        this._ibusCaret = this._ibusWindow = null;
    }

    _setIBusCaret(rect) {
        this._ibusCaret = {x: rect.x, y: rect.y, height: rect.height};
        this._ibusWindow = global.display.focus_window;
        this._refreshCaret();
    }

    _validCaret(rect) {
        if (!rect || ![rect.x, rect.y, rect.height].every(Number.isFinite) ||
            rect.height <= 0 || rect.height > 256)
            return false;
        const frame = this._sessionWindow?.get_frame_rect();
        return !frame || (rect.x >= frame.x && rect.x <= frame.x + frame.width &&
            rect.y >= frame.y && rect.y < frame.y + frame.height);
    }

    _preferredCaret() {
        const native = this._nativeWindow === this._sessionWindow && Main.inputMethod.currentFocus &&
            this._nativeFocus === Main.inputMethod.currentFocus ? this._nativeCaret : null;
        const ibus = this._ibusWindow === this._sessionWindow ? this._ibusCaret : null;
        return [native, ibus, this._sessionCaret].find(rect => this._validCaret(rect)) || null;
    }

    _refreshCaret() {
        if (this._hudIsShowing() && this._phase !== 'returning' &&
            this._sessionWindow === global.display.focus_window) {
            const rect = this._preferredCaret();
            if (rect) this._placeHud(rect);
        }
    }

    _placeHud(rect) {
        const win = this._sessionWindow;
        let monitor = win ? win.get_monitor() : global.display.get_current_monitor();
        if (rect && Number.isFinite(rect.x) && Number.isFinite(rect.y)) {
            const index = Main.layoutManager.monitors.findIndex(m =>
                rect.x >= m.x && rect.x < m.x + m.width && rect.y >= m.y && rect.y < m.y + m.height);
            if (index >= 0) monitor = index;
        }
        const work = Main.layoutManager.getWorkAreaForMonitor(monitor);
        const valid = rect && [rect.x, rect.y, rect.height].every(Number.isFinite) &&
            rect.height > 0 && rect.height <= 256 && rect.x >= work.x &&
            rect.x <= work.x + work.width && rect.y >= work.y && rect.y <= work.y + work.height;
        this._anchored = Boolean(valid);
        if (!valid) {
            const frame = win ? win.get_frame_rect() : work;
            rect = {x: frame.x + frame.width / 2,
                y: Math.min(frame.y + frame.height - 28, work.y + work.height - 28), height: 18};
        }
        this._layout = placement(rect, work);
        const {x, y, width, height, cx, cy} = this._layout;
        this._hudBin.set_position(x, y);
        this._hudBin.set_size(width, height);
        this._core.set_size(width, height);
        this._label.set_position(Math.max(4, cx - 82), cy + 47);
        this._label.set_width(Math.min(164, width - 8));
    }

    _hudIsShowing() {
        return Boolean(this._hudBin && this._hudBin.visible);
    }

    _clearHudTimeout() {
        if (this._hudTimeoutId) {
            GLib.source_remove(this._hudTimeoutId);
            this._hudTimeoutId = 0;
        }
    }

    _startAnim() {
        if (this._animId) return;
        this._lastT = GLib.get_monotonic_time() / 1000;
        // A fixed cap even on 144/240 Hz displays; no idle repaint source.
        this._animId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, Math.ceil(FRAME_MS), () => {
            this._tickOrb();
            return this._animId ? GLib.SOURCE_CONTINUE : GLib.SOURCE_REMOVE;
        });
        this._tickOrb();
    }

    _stopAnim() {
        if (this._animId) GLib.source_remove(this._animId);
        this._animId = 0;
        this._level = this._energy = 0;
    }

    _tickOrb() {
        if (!this._core || !this._hudIsShowing()) return;
        const now = GLib.get_monotonic_time() / 1000;
        const dt = Math.min(0.1, (now - this._lastT) / 1000);
        const target = this._phase === 'listening' ? this._level : 0;
        this._energy += (target - this._energy) * (1 - Math.exp(-(target > this._energy ? 18 : 6) * dt));
        this._lastT = now;
        if (this._label.visible) {
            this._label.opacity = labelOpacity(now - this._labelT0, this._reduced);
            if (!this._label.opacity) this._label.hide();
        }
        if (this._phase === 'returning' && now - this._phaseT0 >= (this._reduced ? 80 : RETURN_MS)) {
            this._completeReturn();
            return;
        }
        // Reduced motion still gives a live meter, at five updates per second.
        if (!this._reduced || !this._lastPaint || now - this._lastPaint >= 200) {
            this._lastPaint = now;
            this._core.queue_repaint();
        }
    }

    _paintOrb(area) {
        let cr = null;
        try {
            if (!this._layout) return;
            cr = area.get_context();
            cr.setAntialias(Cairo.Antialias.GRAY);
            const now = GLib.get_monotonic_time() / 1000;
            drawLens(cr, this._layout, {
                time: this._reduced ? 0 : (now - this._animT0) / 1000,
                energy: this._energy, phase: this._phase,
                progress: (now - this._phaseT0) / (this._phase === 'returning' ? RETURN_MS : ENTER_MS),
                anchored: this._anchored, reduced: this._reduced,
            });
        } catch (e) {
            log(`VoiceLens lens paint failed: ${e}`);
            this._hideHud(true);
        } finally {
            if (cr) cr.$dispose();
        }
    }

    _showHud(label, phase, caret = null) {
        this._ensureHud();
        const fresh = !this._hudIsShowing() || this._phase === 'idle';
        if (fresh) {
            this._sessionWindow = global.display.focus_window;
            this._sessionCaret = caret;
            this._placeHud(this._preferredCaret());
            this._animT0 = this._phaseT0 = GLib.get_monotonic_time() / 1000;
            this._reduced = !this._interfaceSettings.get_boolean('enable-animations');
            this._lastPaint = 0;
        }
        this._hudBin.accessible_name = label || 'VoiceLens';
        if (fresh || this._label.text !== label) {
            this._labelT0 = GLib.get_monotonic_time() / 1000;
            this._label.text = label;
            this._label.opacity = 255;
            this._label.show();
        }
        this._hudBin.remove_all_transitions();
        this._hudBin.opacity = 255;
        this._hudBin.show();
        this._phase = phase;
        this._hudPersist = phase === 'listening';
        this._clearHudTimeout();
        if (phase === 'transcribing') {
            this._enterTranscribing();
        } else {
            this._hudTimeoutId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, HUD_WORK_MS, () => {
                this._hudTimeoutId = 0;
                this._hideHud(true);
                return GLib.SOURCE_REMOVE;
            });
        }
        this._startAnim();
    }

    _hideHud(immediate = false) {
        this._resolveFinish(false);
        this._clearHudTimeout();
        this._hudPersist = false;
        this._phase = 'idle';
        this._stopAnim();
        if (!this._hudBin) return;
        this._hudBin.remove_all_transitions();
        if (immediate || this._reduced) {
            this._hudBin.hide();
            return;
        }
        this._hudBin.ease({opacity: 0, duration: HUD_FADE_MS,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            onComplete: () => this._hudBin?.hide()});
    }

    _destroyHud() {
        this._hideHud(true);
        if (!this._hudBin) return;
        this._core.disconnect(this._repaintId);
        Main.layoutManager.removeChrome(this._hudBin);
        this._hudBin.destroy();
        this._hudBin = this._core = this._label = null;
    }

    _onEvent(_actor, event) {
        try {
            if (this._pasteGuard || Main.sessionMode.isLocked)
                return Clutter.EVENT_PROPAGATE;
            const type = event.type();
            if (type !== Clutter.EventType.KEY_PRESS && type !== Clutter.EventType.KEY_RELEASE)
                return Clutter.EVENT_PROPAGATE;
            if (isRepeated(event))
                return Clutter.EVENT_PROPAGATE;
            const keyval = event.get_key_symbol();
            if (isControl(keyval)) {
                this._setCtrl(type === Clutter.EventType.KEY_PRESS);
                return Clutter.EVENT_PROPAGATE;
            }
            if (this._ctrlHeld && type === Clutter.EventType.KEY_PRESS && !isModifier(keyval))
                this._chord();
        } catch (e) {
            log(`VoiceLens PTT event failed: ${e}`);
        }
        return Clutter.EVENT_PROPAGATE;
    }

    _call(action) {
        Gio.DBus.session.call(
            APP_NAME,
            APP_PATH,
            'org.gtk.Actions',
            'Activate',
            new GLib.Variant('(sava{sv})', [action, [], {}]),
            null,
            Gio.DBusCallFlags.NONE,
            400,
            null,
            (connection, result) => {
                try {
                    connection.call_finish(result);
                } catch (e) {
                    // VoiceLens is not running in the background.
                }
            }
        );
    }
}
