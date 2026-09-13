// Explicit test doubles. Only Cairo and the lens renderer are real.
import NativeGLib from 'gi://GLib';
// LENS_IMPORT
let now = 1000;
let id = 0;
const timers = new Map();
let reduced = false;
let painted = 0;
const GLib = {
    Variant: NativeGLib.Variant,
    PRIORITY_DEFAULT: 0, SOURCE_CONTINUE: true, SOURCE_REMOVE: false,
    get_monotonic_time: () => now * 1000,
    timeout_add: (_priority, ms, callback) => { timers.set(++id, {ms, callback}); return id; },
    source_remove: source => timers.delete(source),
};
function check(condition, label) { if (!condition) throw new Error(label); }
class SignalSource {
    constructor() { this.handlers = new Map(); }
    connect(signal, callback) { this.handlers.set(++id, {signal, callback}); return id; }
    disconnect(source) { this.handlers.delete(source); }
    emit(signal, ...args) {
        for (const handler of this.handlers.values())
            if (handler.signal === signal) handler.callback(this, ...args);
    }
}
class Actor extends SignalSource {
    constructor(props) { super(); Object.assign(this, props); this.visible = false; }
    show() { this.visible = true; }
    hide() { this.visible = false; }
    set_position(x, y) { this.x = x; this.y = y; }
    set_size(w, h) { this.width = w; this.height = h; }
    set_width(w) { this.width = w; }
    add_child() {}
    remove_all_transitions() {}
    ease(options) { options.onComplete?.(); }
    destroy() { this.visible = false; }
    queue_repaint() { painted++; this.emit('repaint'); }
    get_context() { return new Cairo.Context(new Cairo.ImageSurface(Cairo.Format.ARGB32, this.width, this.height)); }
}
const work = {x: -1920, y: 30, width: 1920, height: 1050};
const targetWindow = {get_monitor: () => 0, get_frame_rect: () => work,
    get_compositor_private: () => ({x: -1920, y: 30}), get_wm_class: () => 'ExampleEditor'};
const global = {
    display: Object.assign(new SignalSource(), {focus_window: targetWindow, get_current_monitor: () => 0}),
    stage: new SignalSource(),
    get_pointer: () => [0, 0, 0],
    get_current_time: () => now,
};
const Main = {
    sessionMode: {isLocked: false},
    inputMethod: Object.assign(new SignalSource(), {currentFocus: null}),
    layoutManager: {addChrome(_actor, props) { check(!props.affectsInputRegion, 'overlay must pass through clicks'); },
        removeChrome() {}, monitors: [work], getWorkAreaForMonitor: () => work},
};
const ibus = new SignalSource();
ibus._panelService = new SignalSource();
const IBusManager = {getIBusManager: () => ibus};
const keys = [];
const Clutter = {ModifierType: {}, EventType: {KEY_PRESS: 1, KEY_RELEASE: 2},
    InputDeviceType: {KEYBOARD_DEVICE: 1}, KeyState: {PRESSED: 1, RELEASED: 0},
    KEY_Control_L: 'Control', KEY_Shift_L: 'Shift', KEY_v: 'v',
    get_default_backend: () => ({get_default_seat: () => ({create_virtual_device: () => ({
        notify_keyval: (_time, key, state) => keys.push([key, state]),
    })})}),
    AnimationMode: {EASE_OUT_QUAD: 1}, EVENT_PROPAGATE: 0};
const Gio = {
    Settings: class {get_boolean() { return !reduced; }},
    DBusExportedObject: {wrapJSObject: () => ({export() {}, unexport() {}})},
    DBus: {session: {}}, BusType: {SESSION: 0}, BusNameOwnerFlags: {REPLACE: 0},
    bus_own_name: () => ++id, bus_unown_name() {},
};
let copied = null;
const St = {Widget: Actor, DrawingArea: Actor, Label: Actor,
    ClipboardType: {CLIPBOARD: 1}, Clipboard: {get_default: () => ({set_text: (_kind, text) => { copied = text; }})}};
class Extension {}
function log(message) { throw new Error(message); }
// INSERT_EXTENSION

const app = new VoiceLensPttExtension();
app.enable();
const actions = [];
app._call = action => actions.push(action);
check(timers.size === 1, 'only modifier polling while idle');
check(app.ShowSession('listening', 'Hört zu', -800, 500, 22, true), 'session starts');
check(app._anchored && app._layout.x < 0, 'negative monitor caret remains anchored');
check(timers.get(app._animId).ms >= 1000 / 30, 'frame rate cap');
now += 1999;
app._tickOrb();
check(app._label.visible && app._label.opacity === 255, 'caption fully visible for two seconds');
now += 351;
app._tickOrb();
check(app._label.opacity > 0 && app._label.opacity < 255, 'caption fades gradually');
now += 351;
app._tickOrb();
check(!app._label.visible && app._hudIsShowing(), 'caption disappears while lens stays active');
app.ShowSession('listening', 'Hört zu', -800, 500, 22, true);
check(!app._label.visible, 'duplicate status must not resurrect the caption');
app.SetLevel(0.8);
now += 100;
app._tickOrb();
check(app._energy > 0 && app._energy < 0.8, 'voice envelope smoothing');
app.SetLevel(NaN);
check(app._level === 0.8, 'invalid levels ignored');
app._ctrlHeld = true;
app._setCtrl(false);
check(app._phase === 'transcribing', 'release changes phase immediately');
app.ShowSession('transcribing', 'Transcribing', -800, 500, 22, true);
check(app._label.visible && app._label.opacity === 255, 'new phase briefly shows its own caption');
app._setCtrl(true);
check(app._phase === 'transcribing', 'press while busy does not restart visual recording');
let acknowledgments = [];
app.FinishSessionAsync([], {return_value: v => acknowledgments.push(v.deep_unpack()[0])});
check(acknowledgments.length === 0, 'return must finish before ack');
now += 200;
app._tickOrb();
check(acknowledgments.length === 0 && app._hudIsShowing(), 'return stays visible mid-flight');
now += 230;
app._tickOrb();
check(acknowledgments.length === 1 && acknowledgments[0], 'ack exactly once after return');
check(!app._hudIsShowing() && !app._animId && timers.size === 1, 'all animation timers removed');
check(app._onEvent(null, {type: () => 'motion'}) === Clutter.EVENT_PROPAGATE, 'keys propagate');
app.ShowSession('listening', 'Listening', 0, 0, 0, false);
check(!app._anchored, 'unavailable caret uses window fallback');
ibus.emit('set-cursor-location', {x: -700, y: 450, height: 20});
check(app._anchored && app._layout.x + app._layout.ax === -700, 'IBus anchors Electron without Wayland input focus or AT-SPI');
ibus._panelService.emit('set-cursor-location-relative', 1000, 500, 1, 22);
check(app._layout.x + app._layout.ax === -920 && app._layout.y + app._layout.ay === 541,
    'relative IBus coordinates include compositor window origin');
ibus.emit('focus-out');
check(app._ibusCaret === null, 'IBus focus-out discards stale geometry');
app.HideStatus();
app.ShowSession('listening', 'Listening', -800, 500, 22, true);
Main.inputMethod.currentFocus = {};
Main.inputMethod.emit('cursor-location-changed', {get_x: () => 0, get_y: () => 0, get_height: () => 0});
check(app._anchored && app._layout.x + app._layout.ax === -800, 'invalid native rectangle cannot mask valid AT-SPI caret');
Main.inputMethod.emit('cursor-location-changed', {get_x: () => -650, get_y: () => 480, get_height: () => 20});
check(app._layout.x + app._layout.ax === -650, 'valid Wayland rectangle takes priority');
Main.inputMethod.currentFocus = null;
const oldPanel = ibus._panelService;
ibus._panelService = new SignalSource();
ibus.emit('ready', true);
check(oldPanel.handlers.size === 0 && ibus._panelService.handlers.size === 1, 'IBus restart reconnects relative cursor once');
ibus.emit('set-cursor-location', {x: -600, y: 450, height: 22});
global.display.focus_window = {...targetWindow};
global.display.emit('notify::focus-window');
check(app._ibusCaret === null && app._nativeCaret === null && !app._hudIsShowing(), 'window change invalidates geometry and cancels session');
check(actions.at(-1) === 'ptt-cancel', 'window change cancels application recording');
global.display.focus_window = targetWindow;
app.ShowSession('transcribing', 'Transcribing', 0, 0, 0, false);
acknowledgments = [];
app.FinishSessionAsync([], {return_value: v => acknowledgments.push(v.deep_unpack()[0])});
app.HideStatus();
now += 800;
app._tickOrb();
check(acknowledgments.length === 1 && !acknowledgments[0], 'cancel rejects ack without late completion');
reduced = true;
app.ShowSession('listening', 'Listening', -800, 500, 22, true);
const before = painted;
now += 50;
app._tickOrb();
check(painted === before, 'reduced motion throttles repaint');
app.FinishSessionAsync([], {return_value() {}});
now += 85;
app._tickOrb();
check(!app._hudIsShowing(), 'reduced motion skips flight');
Main.sessionMode.isLocked = true;
check(!app.ShowSession('listening', 'Listening', 0, 0, 20, true), 'no overlay on lockscreen');
Main.sessionMode.isLocked = false;

function fire(source) {
    const timer = timers.get(source);
    check(Boolean(timer), 'scheduled source exists');
    if (!timer.callback()) timers.delete(source);
}
for (const [wmClass, hint, expected] of [
    ['org.gnome.Terminal', false, ['Control', 'Shift', 'v', 'v', 'Shift', 'Control']],
    ['kitty', false, ['Control', 'Shift', 'v', 'v', 'Shift', 'Control']],
    ['Code', true, ['Control', 'Shift', 'v', 'v', 'Shift', 'Control']],
    ['ExampleEditor', false, ['Control', 'v', 'v', 'Control']],
    ['my-terminal-notes', false, ['Control', 'v', 'v', 'Control']],
]) {
    global.display.focus_window = {...targetWindow, get_wm_class: () => wmClass};
    app.ShowSession('listening', 'Listening', -800, 500, 22, true);
    keys.length = 0;
    check(app.PasteWithOptions('Synthetic text', hint), 'paste accepted');
    check(!app.PasteWithOptions('duplicate', hint), 'only one scheduled paste');
    fire(app._pasteId);
    check(JSON.stringify(keys.map(k => k[0])) === JSON.stringify(expected), 'correct paste modifiers for ' + wmClass);
    check(keys.filter(k => k[1] === 1).length === keys.filter(k => k[1] === 0).length, 'all virtual keys released');
    check(copied === 'Synthetic text', 'paste preserves text without appending Enter');
    fire(app._pasteGuardId);
    app.HideStatus();
}
global.display.focus_window = targetWindow;
app.ShowSession('listening', 'Listening', -800, 500, 22, true);
keys.length = 0;
check(app.Paste('Synthetic text'), 'legacy Paste method retained');
global.display.focus_window = {...targetWindow};
fire(app._pasteId);
check(keys.length === 0, 'focus change before delayed paste sends no keys');
fire(app._pasteGuardId);
app.HideStatus();
global.display.focus_window = targetWindow;
app.ShowSession('transcribing', 'Transcribing', -800, 500, 22, true);
acknowledgments = [];
app.FinishSessionAsync([], {return_value: v => acknowledgments.push(v.deep_unpack()[0])});
app.disable();
check(timers.size === 0, 'disable removes every source');
check(ibus.handlers.size === 0 && ibus._panelService.handlers.size === 0 && Main.inputMethod.handlers.size === 0,
    'disable disconnects every geometry subscription');
check(acknowledgments.length === 1 && !acknowledgments[0], 'disable resolves pending D-Bus request');
for (const rect of [
    {x: -1919, y: 31, height: 20}, {x: -1, y: 1055, height: 22},
    {x: -1000, y: 31, height: 20}, {x: -900, y: 550, height: 20},
]) {
    const layout = placement(rect, work);
    check(layout.x >= work.x && layout.y >= work.y &&
        layout.x + layout.width <= work.x + work.width &&
        layout.y + layout.height <= work.y + work.height, 'edge geometry stays on monitor');
    const surface = new Cairo.ImageSurface(Cairo.Format.ARGB32, VIEW, VIEW);
    const cr = new Cairo.Context(surface);
    for (const phase of ['listening', 'transcribing', 'returning']) {
        for (const progress of [0, 0.3, 0.8, 1]) {
            drawLens(cr, layout, {time: 1.2, energy: 0.6, phase, progress, anchored: true, reduced: false});
        }
    }
    cr.$dispose();
}
print('overlay checks passed: lifecycle, frame cap, fallback, edges, reduced motion, native Cairo');
