(function(){
  const base = (window.ENV && window.ENV.VITE_API_BASE) || '';
  if (!base) return;
  const origFetch = window.fetch.bind(window);
  window.fetch = function(resource, init){
    try{
      if (typeof resource === 'string' && resource.startsWith('/api')) {
        resource = base.replace(/\/+$/,'') + resource;
      } else if (resource && resource.url && typeof resource.url === 'string' && resource.url.startsWith('/api')) {
        resource = base.replace(/\/+$/,'') + resource.url;
      }
    }catch(e){}
    return origFetch(resource, init);
  };
})();
