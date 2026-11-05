"""CI helper: mirror a public GitHub app release into this site's own origin."""
import argparse,hashlib,json,re,urllib.request
from pathlib import Path
MAX=1024*1024
def download(url,limit):
    if not url.startswith('https://'):raise ValueError('HTTPS required')
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'StickVario-release-mirror'}),timeout=30) as response:data=response.read(limit+1)
    if len(data)>limit:raise ValueError('asset too large')
    return data
def mirror(repo,tag,dest):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo):raise ValueError('owner/repo required')
    from urllib.parse import quote
    suffix='latest' if tag=='latest' else 'tags/'+quote(tag,safe='')
    release=json.loads(download('https://api.github.com/repos/'+repo+'/releases/'+suffix,512*1024))
    assets={a['name']:a for a in release['assets']}
    doc=json.loads(download(assets['stick-vario.release.json']['browser_download_url'],32768))
    if doc.get('schema')!=1 or doc.get('kind')!='micropython-app' or doc.get('board')!='M5StickS3':raise ValueError('incompatible app manifest')
    app=doc['app']
    if app['url']!='stick_vario_ram.py' or type(app['bytes'])!=int or not 0<app['bytes']<=MAX:raise ValueError('invalid artifact')
    data=download(assets['stick_vario_ram.py']['browser_download_url'],MAX)
    if len(data)!=app['bytes'] or hashlib.sha256(data).hexdigest()!=app['sha256']:raise ValueError('SHA-256 mismatch')
    data.decode('utf-8');dest=Path(dest);dest.mkdir(parents=True,exist_ok=True)
    (dest/'stick_vario_ram.py').write_bytes(data)
    doc['origin']={'repository':repo,'tag':release['tag_name'],'release':release['html_url']}
    (dest/'stick-vario.release.json').write_text(json.dumps(doc,indent=2)+'\n',encoding='utf-8')
    print('Mirrored',repo,release['tag_name'],len(data),'bytes')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('repository');p.add_argument('--tag',default='latest');p.add_argument('--dest',default=str(Path(__file__).parent/'firmware'));a=p.parse_args();mirror(a.repository,a.tag,a.dest)
