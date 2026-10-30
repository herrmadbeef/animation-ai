Claude recommended 


❯ what EC2 instance type do you recommend for this                                                                                                                                
     
● I recommend a g6e.xlarge, or a g6e.2xlarge if you want more system RAM headroom.
  
  ┌──────────────────────┬──────────────┬────────────┬────────────────────────┬────────────────────────────────────────────────────────────────────┐
  │       Instance       │  GPU (VRAM)  │ vCPU / RAM │ ~On-demand (us-east-1) │                              Verdict                               │
  ├──────────────────────┼──────────────┼────────────┼────────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ g6e.xlarge           │ L40S (48 GB) │ 4 / 32 GB  │ ~$1.86/hr              │ Best fit. Runs Wan 2.2 A14B at 720p and LTX-2 comfortably          │
  ├──────────────────────┼──────────────┼────────────┼────────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ g6e.2xlarge          │ L40S (48 GB) │ 8 / 64 GB  │ ~$2.24/hr              │ Same GPU, more RAM for offloading or several models at once        │
  ├──────────────────────┼──────────────┼────────────┼────────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ g6.xlarge            │ L4 (24 GB)   │ 4 / 16 GB  │ ~$0.80/hr              │ Budget option: Wan 5B and LTX-2 run OK, slower; 16 GB RAM is tight │
  ├──────────────────────┼──────────────┼────────────┼────────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ g5.xlarge            │ A10G (24 GB) │ 4 / 16 GB  │ ~$1.00/hr              │ Older, similar to g6, and the RAM is tight                         │
  ├──────────────────────┼──────────────┼────────────┼────────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ p4d / p5 (A100/H100) │ 40–80 GB ×8  │ —          │ $30+/hr                │ Overkill unless you're doing training or batch production          │
  └──────────────────────┴──────────────┴────────────┴────────────────────────┴────────────────────────────────────────────────────────────────────┘
  
  Why g6e: 48 GB of VRAM lets you run the best open models at full quality without heavy quantization or offloading tricks. A 24 GB card works, but it's slower and limits
  resolution and clip length.
  
  Before you launch:
  1. Request a GPU quota increase. New accounts often have a limit of 0 vCPUs for G instances. Go to Service Quotas → EC2 → "Running On-Demand G and VT instances" and request at
     least 8. Approval can take hours to days.
  2. Choose the AMI: "Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 22.04/24.04)", which comes with drivers and CUDA ready.
  3. Set storage to 200 GB+ gp3.
  4. Save money: stop the instance when it's idle. Spot pricing is often 50–70% cheaper if interruptions are acceptable. g6e availability varies by region, and us-east-1 and
     us-west-2 are the safest choices.
  
  Prices are approximate, so check the EC2 pricing page (https://aws.amazon.com/ec2/pricing/on-demand/) for your region.
  
  Once the instance is up, I can write a setup script that installs ComfyUI, Wan 2.2 and LTX-2.
