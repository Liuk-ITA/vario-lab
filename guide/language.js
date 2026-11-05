document.getElementById('language').addEventListener('change', event => {
  const language=event.target.value.includes('/it/')?'it':'en';
  try{localStorage.setItem('vibevario.language',language);}catch{}
  window.location.assign(event.target.value);
});
