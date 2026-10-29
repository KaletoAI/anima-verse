shader_type canvas_item;
render_mode unshaded;

void fragment() {
    vec4 tint = COLOR;
    vec3 color = vec3(11.0, 9.0, 6.0) / 255.0;
    float lower = clamp(1.0 - length((UV - vec2(0.5, 1.2)) / vec2(1.2, 0.9)) / 0.7, 0.0, 1.0);
    color = mix(color, vec3(60.0, 44.0, 24.0) / 255.0, lower * 0.35);
    float upper = clamp(1.0 - length((UV - vec2(0.5, 0.38)) / vec2(0.7, 0.55)) / 0.7, 0.0, 1.0);
    color = mix(color, vec3(120.0, 92.0, 50.0) / 255.0, upper * 0.22);
    COLOR = vec4(color, 1.0) * tint;
}
