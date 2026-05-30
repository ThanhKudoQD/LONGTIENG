/**
 * AudioTrackTab — voice TTS + nhiều BGM track.
 */
import React, { useState } from 'react'
import { AudioConfig, AudioTrack } from './types'
import { uploadAsset } from './exportApi'

interface Props {
  audio: AudioConfig
  projectId: number
  onChange: (audio: AudioConfig) => void
}

function genId() { return Math.random().toString(36).slice(2, 10) }

function fmtTime(s: number): string {
  if (!isFinite(s) || s < 0) return '0:00'
  const m = Math.floor(s / 60), sec = Math.floor(s % 60)
  return `${m}:${String(sec).padStart(2, '0')}`
}

export default function AudioTrackTab({ audio, projectId, onChange }: Props) {
  const [uploading, setUploading] = useState(false)

  const patch = <K extends keyof AudioConfig>(key: K, value: AudioConfig[K]) => {
    onChange({ ...audio, [key]: value })
  }

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (!f) return
    e.target.value = ''
    setUploading(true)
    try {
      const r = await uploadAsset(projectId, f, 'audio')
      const dur = r.duration || 60
      const tr: AudioTrack = {
        id: genId(),
        name: r.name.replace(/\.[^.]+$/, ''),
        file_path: r.url,         // url BE
        file_url: r.url,          // dùng cho <audio> preview
        start_time: 0,
        end_time: dur,
        duration_orig: dur,
        volume: 0.3,
        fade_in: 1, fade_out: 2,
        loop: false,
      }
      onChange({ ...audio, tracks: [...audio.tracks, tr] })
    } catch (err: any) {
      alert('Upload thất bại: ' + (err?.response?.data?.detail || err?.message || ''))
    } finally {
      setUploading(false)
    }
  }

  const updateTrack = (id: string, p: Partial<AudioTrack>) => {
    onChange({ ...audio, tracks: audio.tracks.map(t => t.id === id ? { ...t, ...p } : t) })
  }

  const removeTrack = (id: string) => {
    onChange({ ...audio, tracks: audio.tracks.filter(t => t.id !== id) })
  }

  return (
    <div className="max-w-3xl space-y-5">
      {/* Voice TTS */}
      <div className="surface-card p-4">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h3 className="text-[13px] font-semibold">Voice TTS (audio chính)</h3>
            <p className="text-[11px] text-zinc-500">Audio sinh từ pipeline TTS — chèn theo timing mỗi sub.</p>
          </div>
          <label className="flex items-center gap-2 text-[12px]">
            <input type="checkbox" checked={audio.voice_enabled}
              onChange={e => patch('voice_enabled', e.target.checked)} className="w-4 h-4" />
            Bật
          </label>
        </div>
        {audio.voice_enabled && (
          <div>
            <label className="block text-[11px] text-zinc-500 mb-1.5 uppercase tracking-wider font-medium">
              Âm lượng voice: {Math.round(audio.voice_volume * 100)}%
            </label>
            <input type="range" min={0} max={1.5} step={0.05} value={audio.voice_volume}
              onChange={e => patch('voice_volume', parseFloat(e.target.value))}
              className="w-full" />
          </div>
        )}
      </div>

      {/* Ducking */}
      <div className="surface-card p-4">
        <label className="flex items-center gap-2 mb-2 cursor-pointer">
          <input type="checkbox" checked={audio.ducking_enabled}
            onChange={e => patch('ducking_enabled', e.target.checked)} className="w-4 h-4" />
          <span className="text-[13px] font-semibold">Auto ducking BGM khi voice nói</span>
        </label>
        <p className="text-[11px] text-zinc-500 mb-2">Tự giảm âm lượng BGM khi có voice phát → giọng rõ hơn.</p>
        {audio.ducking_enabled && (
          <div>
            <label className="block text-[11px] text-zinc-500 mb-1 uppercase tracking-wider font-medium">
              Mức giảm BGM: -{Math.round(audio.ducking_amount * 100)}%
            </label>
            <input type="range" min={0.1} max={0.9} step={0.05} value={audio.ducking_amount}
              onChange={e => patch('ducking_amount', parseFloat(e.target.value))}
              className="w-full" />
          </div>
        )}
      </div>

      {/* BGM tracks */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <div>
            <h3 className="text-[14px] font-semibold">BGM / Sound Effect</h3>
            <p className="text-[12px] text-zinc-500">Thêm nhiều track nhạc nền/hiệu ứng. Mix tự động với voice.</p>
          </div>
          <label className={`btn text-[12px] cursor-pointer ${uploading ? 'opacity-60 pointer-events-none' : ''}`}>
            {uploading ? '⏳ Đang upload...' : '📁 Upload audio'}
            <input type="file" accept="audio/*" onChange={handleUpload} disabled={uploading} className="hidden" />
          </label>
        </div>

        {audio.tracks.length === 0 ? (
          <div className="text-center py-10 border border-dashed border-zinc-300 dark:border-zinc-700 rounded-lg">
            <div className="text-3xl mb-2">♪</div>
            <div className="text-[13px] text-zinc-500">Chưa có BGM. Bấm "Upload audio" để thêm.</div>
          </div>
        ) : (
          <div className="space-y-3">
            {audio.tracks.map((t, i) => (
              <div key={t.id} className="surface-card p-3">
                <div className="flex items-center gap-2 mb-3">
                  <span className="text-[11px] font-mono text-zinc-400 w-4">{i + 1}</span>
                  <input type="text" value={t.name}
                    onChange={e => updateTrack(t.id, { name: e.target.value })}
                    className="flex-1 px-2 py-1 text-[13px] border border-zinc-200 dark:border-zinc-700 rounded bg-white dark:bg-zinc-950" />
                  {t.file_url && (
                    <audio src={t.file_url} controls preload="none"
                      className="h-7" style={{ width: 180 }} />
                  )}
                  <button onClick={() => removeTrack(t.id)}
                    className="text-[11px] text-red-600 hover:text-red-700 px-1.5 py-1 hover:bg-red-50 rounded">🗑</button>
                </div>

                <div className="grid grid-cols-4 gap-3">
                  <div>
                    <Label>Bắt đầu (giây)</Label>
                    <input type="number" min={0} step={0.5} value={t.start_time}
                      onChange={e => updateTrack(t.id, { start_time: parseFloat(e.target.value) || 0 })}
                      className="input w-full text-[12px]" />
                  </div>
                  <div>
                    <Label>Kết thúc (giây)</Label>
                    <input type="number" min={0} step={0.5} value={t.end_time}
                      onChange={e => updateTrack(t.id, { end_time: parseFloat(e.target.value) || 0 })}
                      className="input w-full text-[12px]" />
                    <div className="text-[10px] text-zinc-400 mt-0.5">
                      ≈ {fmtTime(t.end_time - t.start_time)}
                    </div>
                  </div>
                  <div>
                    <Label>Âm lượng: {Math.round(t.volume * 100)}%</Label>
                    <input type="range" min={0} max={1.5} step={0.05} value={t.volume}
                      onChange={e => updateTrack(t.id, { volume: parseFloat(e.target.value) })}
                      className="w-full" />
                  </div>
                  <div>
                    <Label>Loop nếu ngắn?</Label>
                    <label className="flex items-center gap-1 mt-1 text-[12px]">
                      <input type="checkbox" checked={t.loop}
                        onChange={e => updateTrack(t.id, { loop: e.target.checked })}
                        className="w-4 h-4" />
                      Lặp lại
                    </label>
                  </div>
                  <div>
                    <Label>Fade in: {t.fade_in}s</Label>
                    <input type="range" min={0} max={5} step={0.1} value={t.fade_in}
                      onChange={e => updateTrack(t.id, { fade_in: parseFloat(e.target.value) })}
                      className="w-full" />
                  </div>
                  <div>
                    <Label>Fade out: {t.fade_out}s</Label>
                    <input type="range" min={0} max={5} step={0.1} value={t.fade_out}
                      onChange={e => updateTrack(t.id, { fade_out: parseFloat(e.target.value) })}
                      className="w-full" />
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function Label({ children }: { children: React.ReactNode }) {
  return <label className="block text-[10px] text-zinc-500 mb-1 uppercase tracking-wider font-medium">{children}</label>
}
