import pandas as pd
from utils.pick_line_standard import reclassify_mislabeled_discount_standards
df = pd.DataFrame([
  {"player":"Aja","prop_norm":"pts","line":15.5,"pick_type":"Standard"},
  {"player":"Aja","prop_norm":"pts","line":25.5,"pick_type":"Standard"},
  {"player":"Aja","prop_norm":"pts","line":35.5,"pick_type":"Demon"},
  {"player":"Paige","prop_norm":"pts","line":17.5,"pick_type":"Goblin"},
  {"player":"Paige","prop_norm":"pts","line":22.5,"pick_type":"Standard"},
  {"player":"Paige","prop_norm":"pts","line":39.5,"pick_type":"Demon"},
])
out,n=reclassify_mislabeled_discount_standards(df)
print("changed",n)
print(out.to_string(index=False))
