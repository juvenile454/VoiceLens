// Synthetic scene using the production Cairo renderer. No Shell or audio I/O.
import GLib from 'gi://GLib';
import {VIEW, ENTER_MS, RETURN_MS, placement, drawLens, labelOpacity} from '../gnome-shell-extension/lens.js';
const Cairo = imports.cairo;
const STRINGS = {
    de: {
        title: 'VoiceLens  /  Cursor-Flow',
        eyebrow: 'NOTIZEN',
        heading: 'Eine Idee wird zu Text.',
        prefix: 'Ich habe eine Idee. ',
        suffix: 'Lass sie uns umsetzen.',
        listening: 'VoiceLens · Hört zu',
        transcribing: 'VoiceLens · Transkribiert',
        capListening: 'Steuerung halten · Sprechen',
        capTranscribing: 'Steuerung loslassen · Transkribiert lokal',
        capReturning: 'Zurück zum Cursor',
        capDone: 'Text ist eingefügt.',
        footer: 'Synthetische Vorschau · Original-Zeichenroutine',
    },
    en: {
        title: 'VoiceLens  /  Cursor flow',
        eyebrow: 'NOTES',
        heading: 'An idea becomes text.',
        prefix: 'I have an idea. ',
        suffix: "Let's build it.",
        listening: 'VoiceLens · Listening',
        transcribing: 'VoiceLens · Transcribing',
        capListening: 'Hold Control · Speak',
        capTranscribing: 'Release Control · Transcribing locally',
        capReturning: 'Back to the caret',
        capDone: 'Text inserted.',
        footer: 'Synthetic preview · production renderer',
    },
};
const usage = 'Usage: gjs -m tests/preview_overlay.js OUTPUT_DIRECTORY [en|de]';
if (ARGV.length < 1 || ARGV.length > 2) throw new Error(usage);
const output = ARGV[0];
const S = STRINGS[ARGV[1] ?? 'de'];
if (!S) throw new Error(usage);
GLib.mkdir_with_parents(output, 0o755);
const width = 640, height = 360, fps = 20;
const {prefix, suffix} = S;
const measure = new Cairo.Context(new Cairo.ImageSurface(Cairo.Format.ARGB32, 1, 1));
measure.selectFontFace('Sans', Cairo.FontSlant.NORMAL, Cairo.FontWeight.NORMAL);
measure.setFontSize(18);
const anchorX = 50 + measure.textExtents(prefix).xAdvance;
const finalX = anchorX + measure.textExtents(suffix).xAdvance;
measure.$dispose();
const layout = placement({x: anchorX, y: 235, height: 20}, {x: 0, y: 0, width, height});
function text(cr, value, x, y, size, color) {
    cr.selectFontFace('Sans', Cairo.FontSlant.NORMAL, Cairo.FontWeight.NORMAL);
    cr.setFontSize(size);
    cr.setSourceRGB(...color);
    cr.moveTo(x, y);
    cr.showText(value);
}
for (let frame = 0; frame < fps * 7; frame++) {
    const t = frame / fps;
    const surface = new Cairo.ImageSurface(Cairo.Format.ARGB32, width, height);
    const cr = new Cairo.Context(surface);
    cr.setSourceRGB(0.06, 0.09, 0.12); cr.paint();
    cr.setSourceRGB(0.09, 0.13, 0.17); cr.rectangle(28, 50, 584, 242); cr.fill();
    text(cr, S.title, 30, 30, 14, [0.64, 0.83, 0.81]);
    text(cr, S.eyebrow, 50, 80, 11, [0.55, 0.68, 0.73]);
    text(cr, S.heading, 50, 113, 24, [0.92, 0.97, 0.97]);
    const done = t >= 5.42;
    text(cr, prefix, 50, 251, 18, [0.87, 0.94, 0.95]);
    if (done) text(cr, suffix, anchorX, 251, 18, [0.64, 0.94, 0.85]);
    cr.setSourceRGBA(0.7, 0.94, 0.87, 1);
    const cursorX = done ? finalX : anchorX;
    cr.rectangle(cursorX, 235, 1.5, 20); cr.fill();
    const phase = t < 3 ? 'listening' : t < 5 ? 'transcribing' : 'returning';
    if (!done) {
        const layer = new Cairo.ImageSurface(Cairo.Format.ARGB32, VIEW, VIEW);
        const lens = new Cairo.Context(layer);
        drawLens(lens, layout, {
            time: t, phase,
            energy: t < 3 ? Math.max(0, Math.sin(t * 5) * Math.sin(t * 2.3)) * 0.8 : 0,
            progress: phase === 'returning' ? (t - 5) * 1000 / RETURN_MS : t * 1000 / ENTER_MS,
            anchored: true, reduced: false,
        });
        lens.$dispose();
        cr.setSourceSurface(layer, layout.x, layout.y); cr.paint();
        const opacity = phase === 'returning' ? 0 : labelOpacity((t - (phase === 'transcribing' ? 3 : 0)) * 1000, false) / 255;
        if (opacity) {
            cr.save();
            cr.pushGroup();
            const x = layout.x + layout.cx - 82, y = layout.y + layout.cy + 47;
            const radius = 12, w = 164, h = 26;
            cr.newPath();
            cr.arc(x + w - radius, y + radius, radius, -Math.PI / 2, 0);
            cr.arc(x + w - radius, y + h - radius, radius, 0, Math.PI / 2);
            cr.arc(x + radius, y + h - radius, radius, Math.PI / 2, Math.PI);
            cr.arc(x + radius, y + radius, radius, Math.PI, Math.PI * 1.5);
            cr.closePath();
            cr.setSourceRGBA(0.05, 0.09, 0.12, 0.94); cr.fillPreserve();
            cr.setSourceRGBA(0.52, 0.90, 0.82, 0.26); cr.setLineWidth(1); cr.stroke();
            const label = phase === 'listening' ? S.listening : S.transcribing;
            cr.setFontSize(11);
            text(cr, label, x + (w - cr.textExtents(label).xAdvance) / 2, y + 17, 11, [0.86, 0.98, 0.95]);
            cr.popGroupToSource(); cr.paintWithAlpha(opacity);
            cr.restore();
        }
    }
    const caption = done ? S.capDone : phase === 'listening' ? S.capListening
        : phase === 'transcribing' ? S.capTranscribing : S.capReturning;
    text(cr, caption, 30, 324, 14, [0.77, 0.9, 0.87]);
    text(cr, S.footer, 30, 347, 10, [0.43, 0.57, 0.64]);
    surface.writeToPNG(`${output}/${String(frame).padStart(3, '0')}.png`);
    cr.$dispose();
}
print(`Rendered ${fps * 7} synthetic frames to ${output}`);
