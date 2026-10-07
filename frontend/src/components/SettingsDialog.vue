<script setup lang="ts">
import { ref } from 'vue'
import { state, updateSettings } from '../store'
import Modal from './Modal.vue'

const emit = defineEmits<{ close: [] }>()
const s = state.settings!

const replacement = ref(s.replacement)
const multivalue = ref(s.multivalue_fields.join('; '))
const id3 = ref(s.id3_version)
const albumArtistKey = ref(s.vorbis_albumartist_key)
const padding = ref(s.track_padding)
const coverName = ref(s.cover_name)

async function saveAndClose() {
  await updateSettings({
    replacement: replacement.value,
    multivalue_fields: multivalue.value
      .split(';')
      .map((f) => f.trim().toUpperCase())
      .filter(Boolean),
    id3_version: id3.value,
    vorbis_albumartist_key: albumArtistKey.value,
    track_padding: padding.value,
    cover_name: coverName.value,
  })
  emit('close')
}
</script>

<template>
  <Modal title="Settings" width="620px" @close="emit('close')">
    <div class="form">
      <label for="s-repl">Replace illegal file name characters with</label>
      <div>
        <input id="s-repl" v-model="replacement" maxlength="3" style="width: 60px" />
        <p class="muted">Used for <code>/ \ : * ? " &lt; &gt; |</code> found in tag values when moving files.</p>
      </div>

      <label for="s-multi">Multi-value fields</label>
      <div>
        <input id="s-multi" v-model="multivalue" style="width: 100%" />
        <p class="muted">
          In these fields, <code>;</code> separates values when you edit them. Other fields keep semicolons as text.
        </p>
      </div>

      <label for="s-id3">ID3v2 version for MP3</label>
      <select id="s-id3" v-model.number="id3">
        <option :value="4">ID3v2.4 (foobar2000 default)</option>
        <option :value="3">ID3v2.3 (older players, Windows Explorer)</option>
      </select>

      <label for="s-aa">Album artist key in FLAC/Ogg</label>
      <select id="s-aa" v-model="albumArtistKey">
        <option value="ALBUMARTIST">ALBUMARTIST (Picard, most players)</option>
        <option value="ALBUM ARTIST">ALBUM ARTIST (foobar2000)</option>
      </select>

      <label for="s-cover">Folder image name</label>
      <div>
        <input id="s-cover" v-model="coverName" style="width: 140px" /> <span class="muted">.jpg / .png</span>
        <p class="muted">
          Used for MusicBrainz covers and for covers extracted from embedded pictures. Only one folder image is kept.
        </p>
      </div>

      <label for="s-pad">Track number digits</label>
      <div>
        <input id="s-pad" v-model.number="padding" type="number" min="0" max="4" style="width: 60px" />
        <p class="muted">Used by auto track number and MusicBrainz. 2 gives 01, 02…</p>
      </div>
    </div>
    <template #footer>
      <button @click="emit('close')">Cancel</button>
      <button class="primary" @click="saveAndClose">Save</button>
    </template>
  </Modal>
</template>

<style scoped>
.form {
  display: grid;
  grid-template-columns: 220px 1fr;
  gap: 12px 14px;
  align-items: start;
}

.form > label {
  padding-top: 4px;
}

p {
  margin: 4px 0 0;
  font-size: 12px;
}
</style>
