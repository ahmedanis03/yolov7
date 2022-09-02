python train.py --workers 8 --device 0 --batch-size 32 --data data/cbis_ddsm.yaml --img 640 640 --cfg cfg/training/yolov7-custom.yaml --weights 'yolov7_training.pt' --name yolov7-custom --hyp data/hyp.scratch.custom.yaml



wget https://github.com/WongKinYiu/yolov7/releases/download/v0.1/yolov7_training.pt
wget https://github.com/WongKinYiu/yolov7/releases/download/v0.1/yolov7x_training.pt
wget https://github.com/WongKinYiu/yolov7/releases/download/v0.1/yolov7-w6_training.pt
wget https://github.com/WongKinYiu/yolov7/releases/download/v0.1/yolov7-e6_training.pt
wget https://github.com/WongKinYiu/yolov7/releases/download/v0.1/yolov7-d6_training.pt
wget https://github.com/WongKinYiu/yolov7/releases/download/v0.1/yolov7-e6e_training.pt