/* ============================================================================
 * WorldView — shaders.js
 * CesiumJS post-processing shader module: NVG / FLIR / CRT.
 *
 * Plain JS, no imports, no ES modules. Load via <script src="/static/shaders.js">
 * AFTER Cesium.js. Exposes:
 *
 *   init(viewer)                       — create + attach 3 PostProcessStages
 *   window.WorldViewShaders.enable(name)    — 'nvg' | 'flir' | 'crt'
 *   window.WorldViewShaders.disable(name)
 *   window.WorldViewShaders.isEnabled(name) -> boolean
 *   window.WorldViewShaders.getActive()     -> array of enabled names
 *
 * Cesium 1.119 PostProcessStage contract (from the engine source):
 *   - default sampler uniforms are `colorTexture` and `depthTexture`
 *     (NOT u_texture — declaring a custom uniform that Cesium doesn't
 *     know about crashes _setUniforms with "e[c.name] is not a function")
 *   - the varying is `v_textureCoordinates`, declared `in vec2` (ES3)
 *   - the output is `out_FragColor` (ES3 — gl_FragColor is illegal)
 *   - PostProcessStage defaults to enabled:true — we force enabled:false
 * ==========================================================================*/
(function () {
  "use strict";

  var VALID_NAMES = ["nvg", "flir", "crt"];

  var stages = {}; // name -> Cesium.PostProcessStage
  var initialized = false;

  /* ---- fragment shaders (Cesium 1.119 ES3 contract) ---- */

  // Night vision: green monochrome (mix by luminance) + subtle static noise.
  // Cesium 1.119 PostProcessStage contract (from engine source):
  //   - declare `uniform sampler2D colorTexture;` (NOT auto-injected)
  //   - declare `in vec2 v_textureCoordinates;`
  //   - do NOT declare the output — Cesium prepends `out vec4 out_FragColor;`
  //   - use texture() (ES3), write to out_FragColor
  var NVG_FRAGMENT_SHADER = [
    "uniform sampler2D colorTexture;",
    "in vec2 v_textureCoordinates;",
    "",
    "float hash(vec2 p) {",
    "    return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453);",
    "}",
    "",
    "void main() {",
    "    vec4 color = texture(colorTexture, v_textureCoordinates);",
    "    float luma = dot(color.rgb, vec3(0.299, 0.587, 0.114));",
    "    vec3 nvg = mix(color.rgb, vec3(0.0, luma, 0.0), 0.92);",
    "    float noise = (hash(gl_FragCoord.xy) - 0.5) * 0.10;",
    "    out_FragColor = vec4(nvg + noise, color.a);",
    "}"
  ].join("\n");

  // Thermal: map luminance to palette deep blue -> cyan -> yellow -> red.
  var FLIR_FRAGMENT_SHADER = [
    "uniform sampler2D colorTexture;",
    "in vec2 v_textureCoordinates;",
    "",
    "void main() {",
    "    vec4 color = texture(colorTexture, v_textureCoordinates);",
    "    float luma = dot(color.rgb, vec3(0.299, 0.587, 0.114));",
    "    vec3 cold = vec3(0.0, 0.0, 0.55);",
    "    vec3 cool = vec3(0.0, 0.85, 0.85);",
    "    vec3 warm = vec3(1.0, 1.0, 0.0);",
    "    vec3 hot  = vec3(1.0, 0.0, 0.0);",
    "    vec3 thermal;",
    "    if (luma < 0.33) {",
    "        thermal = mix(cold, cool, luma / 0.33);",
    "    } else if (luma < 0.66) {",
    "        thermal = mix(cool, warm, (luma - 0.33) / 0.33);",
    "    } else {",
    "        thermal = mix(warm, hot, (luma - 0.66) / 0.34);",
    "    }",
    "    out_FragColor = vec4(thermal, color.a);",
    "}"
  ].join("\n");

  // CRT: horizontal scanlines (sin of y) + vignette (darken edges).
  var CRT_FRAGMENT_SHADER = [
    "uniform sampler2D colorTexture;",
    "in vec2 v_textureCoordinates;",
    "",
    "void main() {",
    "    vec4 color = texture(colorTexture, v_textureCoordinates);",
    "    float scanline = 0.85 + 0.15 * sin(v_textureCoordinates.y * 3.14159265 * 240.0);",
    "    vec2 off = v_textureCoordinates - 0.5;",
    "    float vignette = 1.0 - dot(off, off) * 1.5;",
    "    out_FragColor = vec4(color.rgb * scanline * vignette, color.a);",
    "}"
  ].join("\n");

  var SHADER_BY_NAME = {
    nvg: NVG_FRAGMENT_SHADER,
    flir: FLIR_FRAGMENT_SHADER,
    crt: CRT_FRAGMENT_SHADER
  };

  function isValidName(name) {
    return VALID_NAMES.indexOf(name) !== -1;
  }

  /**
   * Create the three PostProcessStages and attach them to the viewer's scene.
   * Idempotent: calling twice is a no-op. All stages start DISABLED.
   */
  function init(viewer) {
    if (initialized) {
      return;
    }
    if (!viewer || !viewer.scene || !Cesium || !Cesium.PostProcessStage) {
      throw new Error("WorldViewShaders.init: valid Cesium viewer required");
    }
    VALID_NAMES.forEach(function (name) {
      var stage = new Cesium.PostProcessStage({
        fragmentShader: SHADER_BY_NAME[name],
        enabled: false // CRITICAL: PostProcessStage defaults to enabled:true
      });
      viewer.scene.postProcessStages.add(stage);
      // Cesium 1.119 QUIRK: the constructor `enabled:false` option is
      // IGNORED — stages start ENABLED (that's the green world bug: NVG
      // was tinting everything at boot). Force-disable AFTER creation —
      // the only reliable way.
      stage.enabled = false;
      stages[name] = stage;
    });
    initialized = true;
  }

  function enable(name) {
    if (!isValidName(name)) {
      console.warn("WorldViewShaders.enable: unknown shader '" + name + "' (expected nvg|flir|crt)");
      return;
    }
    if (!initialized) {
      console.warn("WorldViewShaders.enable: call init(viewer) first");
      return;
    }
    stages[name].enabled = true;
  }

  function disable(name) {
    if (!isValidName(name)) {
      console.warn("WorldViewShaders.disable: unknown shader '" + name + "' (expected nvg|flir|crt)");
      return;
    }
    if (!initialized) {
      console.warn("WorldViewShaders.disable: call init(viewer) first");
      return;
    }
    stages[name].enabled = false;
  }

  function isEnabled(name) {
    if (!isValidName(name) || !initialized) {
      return false;
    }
    return stages[name].enabled === true;
  }

  function getActive() {
    return VALID_NAMES.filter(function (name) {
      return isEnabled(name);
    });
  }

  window.WorldViewShaders = {
    init: init,
    enable: enable,
    disable: disable,
    isEnabled: isEnabled,
    getActive: getActive
  };
})();
