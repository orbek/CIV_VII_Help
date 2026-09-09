/* Pure decisions about the tactical view, with no DOM.

   The old map fitted every known city tile and up to twelve contacts into one viewBox.
   With settlements on two continents that meant a picture of the ocean between them, with
   each frontier too small to read; and the thirteenth contact simply did not exist. These
   functions are the fix, and they are here rather than inline so they can be executed and
   asserted (tests/test_web_tactical.py runs this file under node). */
(function (root) {
  "use strict";

  var ALL = "all";
  var EXPOSED = "exposed";
  var PAGE_SIZE = 12;

  /* The views the player can choose between.

     One per known frontier, plus "All contacts" so nothing is ever unreachable, plus a
     focus for distant exposed units of your own — those get their own view because
     stretching a frontier's bounds to include one shrinks the frontier itself. */
  function views(data) {
    var out = (data.clusters || []).map(function (cluster) {
      var contacts = (data.enemy_units || []).filter(function (u) {
        return u.cluster === cluster.id;
      });
      return {
        id: cluster.id,
        label: cluster.label,
        detail: cluster.tiles.length + " known tile" + (cluster.tiles.length === 1 ? "" : "s")
          + " · " + contacts.length + " contact" + (contacts.length === 1 ? "" : "s"),
        kind: "cluster",
        count: contacts.length,
      };
    });
    var exposed = (data.human_units || []).filter(function (u) { return u.exposed; });
    if (exposed.length) {
      out.push({
        id: EXPOSED,
        label: "Your exposed units",
        detail: exposed.length + " away from any known city area with a rival within reach",
        kind: "exposed",
        count: exposed.length,
      });
    }
    var total = (data.enemy_units || []).length;
    out.push({
      id: ALL,
      label: "All contacts",
      detail: total + " recorded rival position" + (total === 1 ? "" : "s") + ", nearest first",
      kind: "all",
      count: total,
    });
    return out;
  }

  /* What a view contains. `offMap` is the count the picture leaves out, which is stated
     rather than silently dropped. */
  function contents(data, viewId) {
    var enemies = data.enemy_units || [];
    var own = data.human_units || [];
    var clusters = data.clusters || [];
    if (viewId === ALL) {
      var ordered = enemies.slice().sort(byDistance);
      return { tiles: [], contacts: ordered, units: [], goals: data.attack_goals || [],
               offMap: 0, cluster: null };
    }
    if (viewId === EXPOSED) {
      var exposed = own.filter(function (u) { return u.exposed; });
      var keys = {};
      exposed.forEach(function (u) { keys[u.key] = true; });
      var nearby = enemies.filter(function (e) {
        return exposed.some(function (u) { return within(u, e, 4); });
      });
      return { tiles: [], contacts: nearby.slice().sort(byDistance), units: exposed,
               goals: [], offMap: enemies.length - nearby.length, cluster: null };
    }
    var cluster = clusters.filter(function (c) { return c.id === viewId; })[0] || null;
    if (!cluster) return { tiles: [], contacts: [], units: [], goals: [], offMap: 0, cluster: null };
    var mine = enemies.filter(function (u) { return u.cluster === viewId; });
    return {
      tiles: cluster.tiles,
      contacts: mine.slice().sort(byDistance),
      units: own.filter(function (u) { return u.cluster === viewId; }),
      goals: (data.attack_goals || []).filter(function (g) { return g.cluster === viewId; }),
      offMap: enemies.length - mine.length,
      cluster: cluster,
    };
  }

  function byDistance(a, b) {
    var da = a.distance_to_city === null || a.distance_to_city === undefined
      ? Number.MAX_SAFE_INTEGER : a.distance_to_city;
    var db = b.distance_to_city === null || b.distance_to_city === undefined
      ? Number.MAX_SAFE_INTEGER : b.distance_to_city;
    if (da !== db) return da - db;
    if (b.turn !== a.turn) return b.turn - a.turn;
    return a.key < b.key ? -1 : a.key > b.key ? 1 : 0;
  }

  function within(a, b, hexes) {
    return a.x !== null && b.x !== null && hexDistance(a, b) <= hexes;
  }

  function hexDistance(a, b) {
    var axial = function (p) { return { q: p.x - (p.y - (p.y & 1)) / 2, r: p.y }; };
    var aa = axial(a), bb = axial(b), dq = aa.q - bb.q, dr = aa.r - bb.r;
    return (Math.abs(dq) + Math.abs(dr) + Math.abs(dq + dr)) / 2;
  }

  /* A page of the contact table.

     Paging, never truncation: the count and the page controls together mean contact
     thirteen — and contact two hundred — is always reachable. `filter` matches the rival's
     name or the unit type so a crowded frontier can be narrowed without losing anything. */
  function page(contacts, options) {
    var settings = options || {};
    var size = settings.size || PAGE_SIZE;
    var text = (settings.filter || "").trim().toLowerCase();
    var matched = !text ? contacts : contacts.filter(function (c) {
      return (c.name || "").toLowerCase().indexOf(text) !== -1
        || (c.unit_type || "").toLowerCase().indexOf(text) !== -1;
    });
    var pages = Math.max(Math.ceil(matched.length / size), 1);
    var index = Math.min(Math.max(settings.page || 0, 0), pages - 1);
    return {
      rows: matched.slice(index * size, index * size + size),
      page: index,
      pages: pages,
      matched: matched.length,
      total: contacts.length,
      filtered: Boolean(text),
    };
  }

  /* Contacts sharing one tile.

     Two units on the same hex are one marker, so the marker alone cannot be used to pick
     between them. The table lists them separately and selection is driven from there,
     which is also what makes them reachable by keyboard. */
  function coincident(contacts) {
    var byTile = {};
    contacts.forEach(function (c) {
      if (c.x === null || c.x === undefined) return;
      var key = c.x + ":" + c.y;
      (byTile[key] = byTile[key] || []).push(c);
    });
    return Object.keys(byTile).filter(function (key) {
      return byTile[key].length > 1;
    }).map(function (key) {
      return { tile: key, contacts: byTile[key] };
    });
  }

  /* The viewBox for a set of plotted points, and the scale to draw marks at.

     Markers and labels are sized from the span being shown rather than fixed, so a
     two-tile frontier is not drawn with pinhead markers and a forty-tile one is not drawn
     with markers that overlap. */
  function frame(points, options) {
    var settings = options || {};
    var spacingX = settings.spacingX || 42;
    var spacingY = settings.spacingY || 36;
    if (!points.length) return null;
    var projected = points.map(function (p) {
      return { x: (p.x + (p.y & 1) / 2) * spacingX, y: p.y * spacingY };
    });
    var xs = projected.map(function (p) { return p.x; });
    var ys = projected.map(function (p) { return p.y; });
    var pad = spacingX * 0.75;
    var minX = Math.min.apply(null, xs) - pad;
    var maxX = Math.max.apply(null, xs) + pad;
    var minY = Math.min.apply(null, ys) - pad;
    var maxY = Math.max.apply(null, ys) + pad;
    var width = Math.max(maxX - minX, spacingX * 2);
    var height = Math.max(maxY - minY, spacingY * 2);
    /* Marks are a fraction of the span, clamped so they stay legible at both extremes. */
    var unit = Math.max(width, height) / 18;
    return {
      viewBox: [minX, minY, width, height].join(" "),
      width: width,
      height: height,
      tile: clamp(unit, 8, 26),
      marker: clamp(unit * 0.62, 5, 16),
      font: clamp(unit * 0.7, 6, 15),
      stroke: clamp(unit * 0.09, 0.6, 2.4),
    };
  }

  function clamp(value, low, high) {
    return Math.min(Math.max(value, low), high);
  }

  var api = {
    ALL: ALL, EXPOSED: EXPOSED, PAGE_SIZE: PAGE_SIZE,
    views: views, contents: contents, page: page, coincident: coincident,
    frame: frame, hexDistance: hexDistance,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Civ7Tactical = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
