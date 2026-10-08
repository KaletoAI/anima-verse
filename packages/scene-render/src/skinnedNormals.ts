/** Install before material compilation. WebGLRenderer uses WebGL2. */
const installed = new WeakSet<object>()
export function installSkinnedNormalCorrection(three: typeof import('three')): void {
  if (installed.has(three.ShaderChunk)) return
  three.ShaderChunk.skinnormal_vertex = three.ShaderChunk.skinnormal_vertex
    .replace('objectNormal = vec4( skinMatrix * vec4( objectNormal, 0.0 ) ).xyz;',
      'objectNormal = normalize(inverse(transpose(mat3(skinMatrix))) * objectNormal);')
    .replace('objectTangent = vec4( skinMatrix * vec4( objectTangent, 0.0 ) ).xyz;',
      'objectTangent = normalize(mat3(skinMatrix) * objectTangent);')
  installed.add(three.ShaderChunk)
}
