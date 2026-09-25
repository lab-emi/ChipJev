v {xschem version=3.4.5 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
T {sky130-opampN-gain chipjev seed 1: ota5_p+cas_n+miller} 0 -140 0 0 0.5 0.5 {}
T {ChipJev design on SKY130 (TT), VDD = 1.8 V} 0 -100 0 0 0.3 0.3 {}
C {sky130_fd_pr/pfet_01v8.sym} 0 0 0 0 {name=M1 L=0.15 W=11.46 nf=1 mult=1 ad=3.3234 as=3.3234 pd=23.5 ps=23.5 nrd=0.0253054 nrs=0.0253054 sa=0 sb=0 sd=0 model=pfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 20 30 0 0 {name=l1 sig_type=std_logic lab=t1}
C {devices/lab_pin.sym} -20 0 0 0 {name=l2 sig_type=std_logic lab=s1t}
C {devices/lab_pin.sym} 20 -30 0 0 {name=l3 sig_type=std_logic lab=vdd}
C {devices/lab_pin.sym} 20 0 0 0 {name=l4 sig_type=std_logic lab=vdd}
C {sky130_fd_pr/pfet_01v8.sym} 240 0 0 0 {name=M2 L=0.15 W=64.95 nf=2 mult=1 ad=9.41775 as=18.8355 pd=65.53 ps=131.06 nrd=0.00446497 nrs=0.00446497 sa=0 sb=0 sd=0 model=pfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 260 30 0 0 {name=l5 sig_type=std_logic lab=x1}
C {devices/lab_pin.sym} 220 0 0 0 {name=l6 sig_type=std_logic lab=inp}
C {devices/lab_pin.sym} 260 -30 0 0 {name=l7 sig_type=std_logic lab=t1}
C {devices/lab_pin.sym} 260 0 0 0 {name=l8 sig_type=std_logic lab=vdd}
C {sky130_fd_pr/pfet_01v8.sym} 480 0 0 0 {name=M3 L=0.15 W=64.95 nf=2 mult=1 ad=9.41775 as=18.8355 pd=65.53 ps=131.06 nrd=0.00446497 nrs=0.00446497 sa=0 sb=0 sd=0 model=pfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 500 30 0 0 {name=l9 sig_type=std_logic lab=o1}
C {devices/lab_pin.sym} 460 0 0 0 {name=l10 sig_type=std_logic lab=inn}
C {devices/lab_pin.sym} 500 -30 0 0 {name=l11 sig_type=std_logic lab=t1}
C {devices/lab_pin.sym} 500 0 0 0 {name=l12 sig_type=std_logic lab=vdd}
C {sky130_fd_pr/nfet_01v8.sym} 720 0 0 0 {name=M4 L=0.15 W=13.245 nf=1 mult=1 ad=3.84105 as=3.84105 pd=27.07 ps=27.07 nrd=0.0218951 nrs=0.0218951 sa=0 sb=0 sd=0 model=nfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 740 -30 0 0 {name=l13 sig_type=std_logic lab=x1}
C {devices/lab_pin.sym} 700 0 0 0 {name=l14 sig_type=std_logic lab=x1}
C {devices/lab_pin.sym} 740 30 0 0 {name=l15 sig_type=std_logic lab=0}
C {devices/lab_pin.sym} 740 0 0 0 {name=l16 sig_type=std_logic lab=0}
C {sky130_fd_pr/nfet_01v8.sym} 960 0 0 0 {name=M5 L=0.15 W=13.245 nf=1 mult=1 ad=3.84105 as=3.84105 pd=27.07 ps=27.07 nrd=0.0218951 nrs=0.0218951 sa=0 sb=0 sd=0 model=nfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 980 -30 0 0 {name=l17 sig_type=std_logic lab=o1}
C {devices/lab_pin.sym} 940 0 0 0 {name=l18 sig_type=std_logic lab=x1}
C {devices/lab_pin.sym} 980 30 0 0 {name=l19 sig_type=std_logic lab=0}
C {devices/lab_pin.sym} 980 0 0 0 {name=l20 sig_type=std_logic lab=0}
C {sky130_fd_pr/nfet_01v8.sym} 1200 0 0 0 {name=M6 L=1.69667 W=35.2907 nf=1 mult=1 ad=10.2343 as=10.2343 pd=71.1613 ps=71.1613 nrd=0.00821747 nrs=0.00821747 sa=0 sb=0 sd=0 model=nfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 1220 -30 0 0 {name=l21 sig_type=std_logic lab=s2a}
C {devices/lab_pin.sym} 1180 0 0 0 {name=l22 sig_type=std_logic lab=o1}
C {devices/lab_pin.sym} 1220 30 0 0 {name=l23 sig_type=std_logic lab=0}
C {devices/lab_pin.sym} 1220 0 0 0 {name=l24 sig_type=std_logic lab=0}
C {sky130_fd_pr/nfet_01v8.sym} 0 200 0 0 {name=M7 L=1.69667 W=3.02007 nf=1 mult=1 ad=0.875819 as=0.875819 pd=6.62013 ps=6.62013 nrd=0.0960244 nrs=0.0960244 sa=0 sb=0 sd=0 model=nfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 20 170 0 0 {name=l25 sig_type=std_logic lab=out}
C {devices/lab_pin.sym} -20 200 0 0 {name=l26 sig_type=std_logic lab=s2cn}
C {devices/lab_pin.sym} 20 230 0 0 {name=l27 sig_type=std_logic lab=s2a}
C {devices/lab_pin.sym} 20 200 0 0 {name=l28 sig_type=std_logic lab=0}
C {sky130_fd_pr/pfet_01v8.sym} 240 200 0 0 {name=M8 L=1.69667 W=129.625 nf=3 mult=1 ad=25.0609 as=25.0609 pd=173.994 ps=173.994 nrd=0.00223722 nrs=0.00223722 sa=0 sb=0 sd=0 model=pfet_01v8 spiceprefix=X}
C {devices/lab_pin.sym} 260 230 0 0 {name=l29 sig_type=std_logic lab=out}
C {devices/lab_pin.sym} 220 200 0 0 {name=l30 sig_type=std_logic lab=s2ld}
C {devices/lab_pin.sym} 260 170 0 0 {name=l31 sig_type=std_logic lab=vdd}
C {devices/lab_pin.sym} 260 200 0 0 {name=l32 sig_type=std_logic lab=vdd}
C {devices/capa.sym} 480 200 0 0 {name=C9 value=1.77e-13 m=1}
C {devices/lab_pin.sym} 480 170 0 0 {name=l33 sig_type=std_logic lab=out}
C {devices/lab_pin.sym} 480 230 0 0 {name=l34 sig_type=std_logic lab=o1}
C {devices/vsource.sym} 720 200 0 0 {name=VDD value=1.8 m=1}
C {devices/lab_pin.sym} 720 170 0 0 {name=l35 sig_type=std_logic lab=vdd}
C {devices/lab_pin.sym} 720 230 0 0 {name=l36 sig_type=std_logic lab=0}
C {devices/vsource.sym} 960 200 0 0 {name=V_S1T value=0.9775 m=1}
C {devices/lab_pin.sym} 960 170 0 0 {name=l37 sig_type=std_logic lab=s1t}
C {devices/lab_pin.sym} 960 230 0 0 {name=l38 sig_type=std_logic lab=0}
C {devices/vsource.sym} 1200 200 0 0 {name=V_S2CN value=1.47 m=1}
C {devices/lab_pin.sym} 1200 170 0 0 {name=l39 sig_type=std_logic lab=s2cn}
C {devices/lab_pin.sym} 1200 230 0 0 {name=l40 sig_type=std_logic lab=0}
C {devices/vsource.sym} 0 400 0 0 {name=V_S2LD value=0.68 m=1}
C {devices/lab_pin.sym} 0 370 0 0 {name=l41 sig_type=std_logic lab=s2ld}
C {devices/lab_pin.sym} 0 430 0 0 {name=l42 sig_type=std_logic lab=0}
