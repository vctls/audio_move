export type Tags = Record<string, string[]>

export interface TrackInfo {
  codec: string
  codec_profile: string
  length: number
  bitrate: number
  samplerate: number
  channels: number
  bitspersample: number
  encoding: string
  filesize: number
  last_modified: string
}

export interface Picture {
  type: string
  mime: string
  width: number
  height: number
  size: number
}

export interface FolderImage {
  names: string[]
  width: number
  height: number
  size: number
}

export interface Track {
  path: string
  tags: Tags
  info: TrackInfo
  pictures: Picture[]
  folder_image: FolderImage | null
  mtime: number
}

// Field name -> new values, or null when the field is removed.
export type PendingFields = Record<string, string[] | null>

export interface Root {
  name: string
  path: string
}

export interface AppConfig {
  roots: Root[]
  max_tracks: number
}

export interface DirEntry {
  name: string
  path: string
}

export interface DirSummary {
  has_children: boolean
  audio: number
}

export interface TracksResponse {
  tracks: Track[]
  errors: { path: string; error: string }[]
  too_many: boolean
  reason?: 'tracks' | 'folders'
  limit?: number
  forced?: boolean
}

export type Operation = 'move' | 'copy' | 'rename'

export interface Settings {
  patterns: string[]
  pattern: string
  operation: Operation
  destination: string
  move_other_files: boolean
  remove_empty_dirs: boolean
  replacement: string
  cover_name: string
  multivalue_fields: string[]
  id3_version: 3 | 4
  vorbis_albumartist_key: 'ALBUMARTIST' | 'ALBUM ARTIST'
  track_padding: number
  autonumber_total: boolean
  autonumber_per_disc: boolean
  mb_date: 'year' | 'full'
  mb_groups: string[]
  mb_disc_for_single: boolean
  mb_cover: boolean
  mb_cover_size: '500' | '1200' | 'original'
  mb_cover_overwrite: boolean
  guess_patterns: string[]
  format_presets: string[]
}

export interface PlanItem {
  src: string
  dst: string
  kind: 'track' | 'other'
  status: 'ok' | 'unchanged' | 'exists' | 'duplicate' | 'error'
  message: string
}

export interface Plan {
  operation: Operation
  items: PlanItem[]
  warnings: string[]
}

export interface ExecuteResult {
  plan: Plan
  done: PlanItem[]
  removed_dirs: string[]
  journal_id?: string
}

export interface HistoryEntry {
  id: string
  time: string
  operation: Operation
  count: number
  undone: boolean
  sample: { src: string; dst: string } | null
}

export interface MbLabel {
  name: string
  catno: string
}

export interface MbReleaseSummary {
  id: string
  score: number | null
  title: string
  disambiguation: string
  artist: string
  date: string
  country: string
  status: string
  barcode: string
  labels: MbLabel[]
  format: string
  media: { format: string; track_count: number }[]
  track_count: number
  type: string
  secondary_types: string[]
}

export interface MbTrack {
  id: string
  recording_id: string
  position: number
  number: string
  title: string
  artist: string
  length: number
  tags: Tags
}

export interface MbMedium {
  position: number
  format: string
  title: string
  track_count: number
  tracks: MbTrack[]
}

export interface MbRelease extends Omit<MbReleaseSummary, 'media'> {
  cover_art: boolean
  release_group: { id: string; type: string; first_release_date: string }
  media: MbMedium[]
}

export interface MbSearchResult {
  count: number
  offset: number
  releases: MbReleaseSummary[]
  query?: string
}
