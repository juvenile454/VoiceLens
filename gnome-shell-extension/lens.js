// Small Cairo surface; no shaders, textures, blur passes or particle actors.
const Cairo = imports.cairo;
const TAU = Math.PI * 2;
export const VIEW = 228;
export const ENTER_MS = 460;
export const RETURN_MS = 420;
export const FRAME_MS = 1000 / 30;
export const LABEL_HOLD_MS = 2000;
export const LABEL_FADE_MS = 700;
export const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
export const ease = p => { p = clamp(p, 0, 1); return p * p * (3 - 2 * p); };
export const labelOpacity = (elapsed, reduced) => reduced
    ? (elapsed < LABEL_HOLD_MS ? 255 : 0)
    : Math.round(255 * (1 - ease((elapsed - LABEL_HOLD_MS) / LABEL_FADE_MS)));

export function placement(rect, work) {
    const width = Math.min(VIEW, work.width);
    const height = Math.min(VIEW, work.height);
    const x = clamp(rect.x - width / 2, work.x, work.x + work.width - width);
    const above = rect.y - work.y >= 155;
    const y = clamp(rect.y - (above ? 192 : 22), work.y, work.y + work.height - height);
    const ax = clamp(rect.x - x, 2, width - 2);
    const ay = clamp(rect.y + rect.height / 2 - y, 2, height - 2);
    return {x, y, width, height, ax, ay,
        cx: clamp(ax, 70, width - 70),
        cy: clamp(ay + (above ? -86 : 86), 68, height - 66)};
}

function glow(cr, x, y, radius, color, alpha) {
    const grad = new Cairo.RadialGradient(x, y, 0, x, y, radius);
    grad.addColorStopRGBA(0, ...color, alpha);
    grad.addColorStopRGBA(0.38, ...color, alpha * 0.45);
    grad.addColorStopRGBA(1, ...color, 0);
    cr.setSource(grad);
    cr.arc(x, y, radius, 0, TAU);
    cr.fill();
}

export function drawLens(cr, layout, state) {
    const {ax, ay, cx, cy} = layout;
    const {time: t, energy: e, phase, progress, anchored, reduced} = state;
    const work = phase === 'transcribing' ? 1 : 0;
    const returning = phase === 'returning';
    const reveal = reduced ? 1 : returning ? 1 - ease(progress) : ease(progress);
    const travel = anchored ? reveal : 1;
    const x = ax + (cx - ax) * travel;
    const y = ay + (cy - ay) * travel + (reduced ? 0 : Math.sin(t * 1.8) * 2 * reveal);
    const scale = reduced ? 1 : 0.025 + 0.975 * reveal;
    const alpha = reduced ? 1 : Math.min(1, reveal * 4);
    const r = (25 + e * 10) * scale;
    const mint = work ? [0.65, 0.60, 1] : [0.40, 0.98, 0.86];
    const blue = [0.38, 0.55, 1];
    cr.setOperator(Cairo.Operator.CLEAR);
    cr.paint();
    cr.setOperator(Cairo.Operator.OVER);
    cr.setLineCap(Cairo.LineCap.ROUND);

    glow(cr, x, y, r * 2.45, mint, (0.22 + e * 0.16) * alpha);
    glow(cr, x + r * 0.3, y + r * 0.2, r * 1.9, blue, 0.3 * alpha);
    const body = new Cairo.RadialGradient(x - r * 0.3, y - r * 0.4, 0, x, y, r * 1.08);
    body.addColorStopRGBA(0, 0.22, 0.40, 0.47, alpha * 0.95);
    body.addColorStopRGBA(0.72, 0.04, 0.12, 0.20, alpha * 0.92);
    body.addColorStopRGBA(1, ...blue, 0);
    cr.setSource(body);
    cr.arc(x, y, r * 1.08, 0, TAU);
    cr.fill();

    // Three flowing membranes; a fixed number of samples bounds CPU work.
    for (let band = 0; band < 3; band++) {
        const color = band === 1 ? blue : mint;
        cr.newPath();
        for (let i = 0; i <= 72; i++) {
            const a = i / 72 * TAU;
            const wave = Math.sin(a * 3 + t * (work ? 1.5 : 0.9) + band * 1.9);
            const ripple = Math.cos(a * 5 - t * 1.2 + band);
            const radius = r * (0.88 + band * 0.065 + wave * (0.04 + e * 0.12) + ripple * e * 0.045);
            const px = x + Math.cos(a) * radius;
            const py = y + Math.sin(a) * radius * (0.89 + band * 0.04);
            if (i === 0) cr.moveTo(px, py); else cr.lineTo(px, py);
        }
        cr.closePath();
        cr.setSourceRGBA(...color, (0.46 + band * 0.18) * alpha);
        cr.setLineWidth((band === 2 ? 1.35 : 0.8) * scale);
        cr.stroke();
    }

    // Rotating elliptical light ribbons communicate processing without a %.
    cr.save();
    cr.translate(x, y);
    cr.rotate(t * (work ? 1.2 : 0.24));
    cr.scale(1, 0.38 + e * 0.12);
    cr.setSourceRGBA(...mint, 0.5 * alpha);
    cr.setLineWidth(1.5 * scale);
    cr.arc(0, 0, r * 0.74, 0.2, TAU - 0.7);
    cr.stroke();
    cr.restore();
    glow(cr, x - r * 0.12, y - r * 0.12, r * 0.85, mint, 0.50 * alpha);
    glow(cr, x, y, r * 0.36, [0.88, 1, 0.98], (0.68 + e * 0.25) * alpha);
    if (work) {
        cr.setSourceRGBA(...mint, 0.7 * alpha);
        cr.setLineWidth(1.3 * scale);
        for (let i = 0; i < 2; i++) {
            const a = t * 1.8 + i * Math.PI;
            cr.arc(x, y, r * 1.36, a, a + 1.25);
            cr.stroke();
        }
    } else {
        for (let i = 0; i < 5; i++) {
            const bx = x + (i - 2) * 5 * scale;
            const bh = (2 + e * (6 + 5 * Math.sin(t * 7 + i))) * scale;
            cr.setSourceRGBA(0.91, 1, 0.98, 0.80 * alpha);
            cr.setLineWidth(1.6 * scale);
            cr.moveTo(bx, y - bh);
            cr.lineTo(bx, y + bh);
            cr.stroke();
        }
    }
}
