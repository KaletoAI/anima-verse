/** Pure game-clock lighting; colours use Three's linear working space. */
import * as THREE from 'three';

export function gameHourLights(hour: number) {
  const h = ((hour % 24) + 24) % 24;
  // Sun arc: 6:00 = east (0), 12:00 = zenith (PI/2), 18:00 = west (PI)
  const sunAngle = ((h - 6) / 12) * Math.PI;
  const day = THREE.MathUtils.clamp(Math.sin(sunAngle), 0, 1);       // 0 at night, 1 at noon
  const dusk = THREE.MathUtils.clamp(1 - Math.abs(h - 12) / 6, 0, 1);     // closeness to midday

  const noon = new THREE.Color(0xfff2d8);
  const warm = new THREE.Color(0xffb066);   // dawn/dusk red
  const night = new THREE.Color(0x9fb4e0);  // moonlight (cool)
  const sunColor = day > 0.05
    ? warm.clone().lerp(noon, THREE.MathUtils.smoothstep(day, 0.05, 0.45))
    : night.clone();
  const skyDay = new THREE.Color(0x9fc7e8);
  const skyDusk = new THREE.Color(0xe89a63);
  const skyNight = new THREE.Color(0x1a2340);
  const sky = day > 0.15
    ? skyDay.clone()
    : skyNight.clone().lerp(skyDusk, THREE.MathUtils.clamp(day / 0.15, 0, 1) * (dusk > 0.05 ? 1 : 0.3));
  // The blend factor reaches 1 at day=0.15 — a continuous handover to the night branch
  if (day > 0.15 && day < 0.35) sky.lerp(skyDusk, (0.35 - day) / 0.2);
  return { sunAngle, sun: sunColor, sky,
    sunIntensity: .25 + day * 2, hemiIntensity: .35 + day * 1.2,
    fillIntensity: .15 + day * .4 };
}
