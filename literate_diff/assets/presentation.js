(function () {
  "use strict";
  var data = JSON.parse(document.getElementById("ld-data").textContent);
  var view = data.presentation;
  if (view.version !== 1) throw new Error("Unsupported presentation version");
  var escapes = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#x27;" };
  var texts = view.text_sources.map(function (source) {
    var text = source.path.reduce(function (value, key) { return value[key]; }, data);
    if (source.escape) text = text.replace(/[&<>"']/g, function (ch) { return escapes[ch]; });
    // Python offsets are Unicode code points, not JavaScript UTF-16 units.
    return Array.from(text);
  });
  function decode(value) {
    if (Array.isArray(value)) return value.map(decode);
    if (value && typeof value === "object") {
      if (value.$text) return value.$text.map(function (part) {
        return typeof part === "string" ? part : texts[part[0]].slice(part[1], part[2]).join("");
      }).join("");
      var out = {};
      Object.keys(value).forEach(function (key) { out[key] = decode(value[key]); });
      return out;
    }
    return value;
  }
  var rendered = decode(view);
  rendered.html = rendered.html.map(function (part) {
    return typeof part === "number" ? rendered.markup[part] : part;
  }).join("");
  document.getElementById("ld-root").innerHTML = rendered.html;
  window.LD = { data: function () { return data; }, presentation: rendered };
})();
