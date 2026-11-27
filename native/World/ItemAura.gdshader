shader_type spatial;
render_mode unshaded, blend_add, depth_draw_never, cull_disabled;

uniform vec4 aura_color : source_color = vec4(1.0, 0.82, 0.45, 1.0);
uniform float intensity : hint_range(0.0, 2.0) = 0.28;
uniform float pulse_period : hint_range(0.5, 10.0) = 2.5;
uniform float grow_m : hint_range(0.0, 0.05) = 0.004;
uniform bool billboard = false;

void vertex() {
    if (billboard) {
        MODELVIEW_MATRIX = VIEW_MATRIX * mat4(
            vec4(normalize(INV_VIEW_MATRIX[0].xyz), 0.0),
            vec4(normalize(INV_VIEW_MATRIX[1].xyz), 0.0),
            vec4(normalize(INV_VIEW_MATRIX[2].xyz), 0.0),
            MODEL_MATRIX[3]);
        MODELVIEW_MATRIX = MODELVIEW_MATRIX * mat4(
            vec4(length(MODEL_MATRIX[0].xyz), 0.0, 0.0, 0.0),
            vec4(0.0, length(MODEL_MATRIX[1].xyz), 0.0, 0.0),
            vec4(0.0, 0.0, length(MODEL_MATRIX[2].xyz), 0.0),
            vec4(0.0, 0.0, 0.0, 1.0));
        MODELVIEW_NORMAL_MATRIX = mat3(MODELVIEW_MATRIX);
        VERTEX.xy *= 1.06;
    } else {
        VERTEX += NORMAL * grow_m;
    }
}

void fragment() {
    float phase = 0.5 + 0.5 * sin(TIME * (6.28318530718 / max(pulse_period, 0.5)));
    float pulse = mix(0.68, 1.0, phase);
    float rim;
    if (billboard) {
        vec2 edge = abs(UV - vec2(0.5)) * 2.0;
        float d = max(edge.x, edge.y);
        rim = mix(0.25, 1.0, smoothstep(0.35, 1.0, d));
    } else {
        float ndv = abs(dot(normalize(NORMAL), normalize(VIEW)));
        rim = mix(0.22, 1.0, pow(clamp(1.0 - ndv, 0.0, 1.0), 2.0));
    }
    ALBEDO = aura_color.rgb;
    ALPHA = clamp(aura_color.a * intensity * pulse * rim, 0.0, 1.0);
}
