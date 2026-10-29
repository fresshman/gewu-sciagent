import math
h=[218.6108,244.9214,222.3821,220.0729,166.8624]
p=[231.2064,248.8767,255.2973,230.6638,203.7164]
def stats(a):
    n=len(a); m=sum(a)/n
    sd1=math.sqrt(sum((x-m)**2 for x in a)/(n-1))
    sd0=math.sqrt(sum((x-m)**2 for x in a)/n)
    return m, sd1, sd0
hm,hs,hs0=stats(h); pm,ps,ps0=stats(p)
print('h mean %.4f std1 %.4f std0 %.4f'%(hm,hs,hs0))
print('h MJ mean %.4f std %.4f'%(hm*0.004184,hs*0.004184))
print('p mean %.4f std1 %.4f std0 %.4f'%(pm,ps,ps0))
print('p MJ mean %.4f std %.4f'%(pm*0.004184,ps*0.004184))
yt=[2931.0,4138.0,4231.0,3622.0,3403.0,3518.0,3379.0,3972.0,3892.0,3644.0,4099.0,3398.0,5714.0,3593.0]
yp=[2941.0453,3891.2307,4073.5176,3634.8613,3489.0648,3945.9818,3360.4529,4103.8579,3701.9702,4018.7205,4018.6389,3297.2879,5456.3963,3932.5795]
n=len(yt); mt=sum(yt)/n
ss_res=sum((yp[i]-yt[i])**2 for i in range(n))
ss_tot=sum((y-mt)**2 for y in yt)
print('r2 %.4f rmse %.4f mae %.4f'%(1-ss_res/ss_tot,math.sqrt(ss_res/n),sum(abs(yp[i]-yt[i]) for i in range(n))/n))