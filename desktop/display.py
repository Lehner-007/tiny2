"""Human-readable camera responses; protocol identifiers remain internal."""
def response_text(value,tr,level=0):
    prefix='  '*level
    if isinstance(value,dict):
        rows=[]
        for key,item in value.items():
            label=tr('response_'+key)
            if label=='response_'+key:
                label=tr('field_'+key)
            if label=='field_'+key:label=tr('response_details')
            if isinstance(item,(dict,list)):
                rows.append(prefix+label+':')
                rows.append(response_text(item,tr,level+1))
            else:
                if isinstance(item,bool):
                    text=tr('response_success' if key=='ok' and item else 'response_failed' if key=='ok' else 'response_yes' if item else 'response_no')
                elif item is None:text=tr('response_unknown')
                else:
                    if key=='control' and tr('uvc_'+str(item))!='uvc_'+str(item):
                        rows.append(prefix+label+': '+tr('uvc_'+str(item)))
                        continue
                    token='response_value_'+str(item)
                    text=tr(token)
                    if text==token:
                        token='value_'+str(item);text=tr(token)
                        if text==token:text=str(item)
                rows.append(prefix+label+': '+text)
        return '\n'.join(rows)
    if isinstance(value,list):
        return '\n'.join(prefix+str(i+1)+'.\n'+response_text(item,tr,level+1) for i,item in enumerate(value)) or prefix+tr('response_empty')
    return prefix+str(value)
