/**
 * AdminClock — one time-of-day format for the server-rendered admin pages.
 *
 * The twin of `packages/player-ui/src/clockFormat.ts`: same four shapes, same
 * rule that the SYSTEM clock is shown in the configured world timezone and not
 * in the viewer's. Both settings come from `/admin/settings → Server` and are
 * rendered into the page as `data-clock-format` / `data-clock-timezone` on
 * <body> — no fetch, so the very first row is already correct. Changing a
 * setting takes effect on the next page load, like every other setting on a
 * server-rendered page.
 *
 * The 12h/24h decision is made here rather than by `toLocaleString('de-DE')`,
 * which is what these pages used to do: one setting must produce one shape, and
 * a hardcoded locale is not a shape the admin chose.
 */
window.AdminClock = (function () {
  var FORMATS = ['24h', '24h_seconds', '12h', '12h_seconds'];

  function settings() {
    var ds = (document.body && document.body.dataset) || {};
    var fmt = FORMATS.indexOf(ds.clockFormat) >= 0 ? ds.clockFormat : '24h';
    return { format: fmt, timeZone: ds.clockTimezone || 'UTC' };
  }

  function two(n) { return n < 10 ? '0' + n : String(n); }

  /** Hour/minute/second → the configured shape (see the TS twin). */
  function shape(hour, minute, second, fmt) {
    var tail = (fmt === '24h_seconds' || fmt === '12h_seconds') ? ':' + two(second) : '';
    if (fmt === '12h' || fmt === '12h_seconds') {
      var suffix = hour < 12 ? 'AM' : 'PM';
      var h12 = hour % 12 === 0 ? 12 : hour % 12;
      return h12 + ':' + two(minute) + tail + ' ' + suffix;
    }
    return two(hour) + ':' + two(minute) + tail;
  }

  function toDate(value) {
    if (!value) return null;
    var d = value instanceof Date ? value : new Date(value);
    return isNaN(d.getTime()) ? null : d;
  }

  /** The wall-clock numbers an instant has in the configured zone. */
  function zoneParts(d, timeZone) {
    var opts = { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' };
    var parts;
    try {
      opts.timeZone = timeZone;
      parts = new Intl.DateTimeFormat('en-US', opts).formatToParts(d);
    } catch (e) {
      // An unknown zone name reads as UTC, never as the viewer's own zone.
      opts.timeZone = 'UTC';
      parts = new Intl.DateTimeFormat('en-US', opts).formatToParts(d);
    }
    var out = { hour: 0, minute: 0, second: 0 };
    parts.forEach(function (p) {
      if (out.hasOwnProperty(p.type)) out[p.type] = parseInt(p.value, 10) || 0;
    });
    out.hour = out.hour % 24;   // hour12:false renders midnight as 24 in some engines
    return out;
  }

  /** A system stamp → time of day only. '' when unusable. */
  function time(value) {
    var d = toDate(value);
    if (!d) return '';
    var s = settings();
    var p = zoneParts(d, s.timeZone);
    return shape(p.hour, p.minute, p.second, s.format);
  }

  /** Date part in the configured zone (viewer's locale for the order). */
  function date(value, options) {
    var d = toDate(value);
    if (!d) return '';
    var opts = {};
    var src = options || { year: 'numeric', month: '2-digit', day: '2-digit' };
    for (var k in src) if (src.hasOwnProperty(k)) opts[k] = src[k];
    var s = settings();
    try {
      opts.timeZone = s.timeZone;
      return new Intl.DateTimeFormat(undefined, opts).format(d);
    } catch (e) {
      opts.timeZone = 'UTC';
      return new Intl.DateTimeFormat(undefined, opts).format(d);
    }
  }

  /** Date + time of day. '' when unusable, so callers can fall back. */
  function stamp(value, dateOptions) {
    var d = toDate(value);
    if (!d) return '';
    return date(d, dateOptions) + ' ' + time(d);
  }

  return { settings: settings, time: time, date: date, stamp: stamp };
})();
