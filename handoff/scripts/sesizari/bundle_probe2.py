import sys, re
sys.stdout.reconfigure(encoding="utf-8")
t = open(sys.argv[1], encoding="utf-8", errors="replace").read()
i = t.find("StreetLight:277")
s = t.rfind("{", 0, i); e = t.find("}", i)
print("ENUM around StreetLight:", t[max(s-60,0):e+1][:3000])
i = t.find("settings={APP_ENV")
print("\nSETTINGS:", re.sub(r'(TOKEN|KEY|SECRET)([A-Z_]*):window\.env\.[A-Z_]+\?\?"[^"]*"', r'\1\2:<redacted>', t[i:i+3500]))
print("\nembed api calls:", sorted(set(re.findall(r'[`"\'][^`"\']{0,60}embed[^`"\']{0,80}[`"\']', t)))[:60])
for k in ("StreetLight", "streetLight", "street-light", "street_light"):
    print(k, t.count(k))
for m in list(re.finditer("StreetLight", t))[:6]:
    print("  ctx:", t[max(0, m.start()-150): m.end()+150].replace("\n", " "))
print("vue version:", re.findall(r'version:"(3\.\d+\.\d+)"', t)[:3], "| mapbox-gl version hints:", re.findall(r'mapbox-gl-js/v(\d+\.\d+\.\d+)', t)[:3], re.findall(r'"sdk-?version"?[:=]"?(\d+\.\d+\.\d+)', t)[:3])
