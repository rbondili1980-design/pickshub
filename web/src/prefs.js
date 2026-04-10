const KEY = 'pickshub_followed'

export function getFollowed() {
  try { return JSON.parse(localStorage.getItem(KEY)) || [] }
  catch { return [] }
}

export function saveFollowed(list) {
  localStorage.setItem(KEY, JSON.stringify(list))
}
