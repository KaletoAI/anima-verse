shader_type canvas_item;
render_mode unshaded;
uniform vec2 surface_size = vec2(430.0, 440.0);

void fragment() {
    vec4 tint = COLOR;
    // CSS's 163 degree gradient line, including the plate's changing aspect ratio.
    vec2 direction = vec2(0.292372, 0.956305);
    float t = clamp(0.5 + dot((UV - 0.5) * surface_size, direction) / dot(surface_size, abs(direction)), 0.0, 1.0);
    vec3 color = t < 0.46
        ? mix(vec3(42.0, 35.0, 25.0), vec3(34.0, 28.0, 20.0), t / 0.46) / 255.0
        : mix(vec3(34.0, 28.0, 20.0), vec3(25.0, 20.0, 16.0), (t - 0.46) / 0.54) / 255.0;
    float lower = clamp(1.0 - length((UV - vec2(0.88, 1.0)) / vec2(0.95, 0.7)) / 0.66, 0.0, 1.0);
    color = mix(color, vec3(96.0, 70.0, 38.0) / 255.0, lower * 0.16);
    float upper = clamp(1.0 - length((UV - vec2(0.18, 0.0)) / vec2(1.15, 0.8)) / 0.62, 0.0, 1.0);
    color = mix(color, vec3(140.0, 110.0, 66.0) / 255.0, upper * 0.16);

    vec2 pixel = UV * surface_size;
    vec2 edge = min(pixel, surface_size - pixel);
    color *= 1.0 - 0.5 * (1.0 - smoothstep(0.0, 40.0, min(edge.x, edge.y)));
    vec2 q = abs(pixel - surface_size * 0.5) - (surface_size * 0.5 - 4.0);
    float distance = length(max(q, vec2(0.0))) + min(max(q.x, q.y), 0.0) - 4.0;
    float border = smoothstep(-1.5, -0.5, distance);
    color = mix(color, vec3(242.0, 205.0, 110.0) / 255.0, border * 0.38);
    color = mix(color, vec3(242.0, 205.0, 110.0) / 255.0, (1.0 - smoothstep(1.0, 2.5, pixel.y)) * 0.14);
    COLOR = vec4(color, 1.0 - smoothstep(-0.5, 0.5, distance)) * tint;
}
