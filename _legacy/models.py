# 1. 哈希表 (Hash Table)

class HashTable:
    def __init__(self, size=64):
        self.size = size    
        self.table = [[] for _ in range(size)]      # 初始化哈希表

    def _hash(self, key):
        return hash(key) % self.size                # 计算哈希值


    def put(self, key, value):
        index = self._hash(key)          
        bucket = self.table[index]       

        for i, (k, v) in enumerate(bucket):
            if k == key:
                bucket[i] = (key, value)  
                return
        bucket.append((key, value))                 # 插入

    def get(self, key, default=None):
        index = self._hash(key)
        bucket = self.table[index]

        for k, v in bucket:
            if k == key:
                return v
        return default                              # 查找

    def remove(self, key):
        index = self._hash(key)
        bucket = self.table[index]

        for i, (k, v) in enumerate(bucket):
            if k == key:
                bucket.pop(i)   
                return True
        return False                                # 删除

    def contains(self, key):
        return self.get(key) is not None             # 是否存在

    def get_all(self):
        result = []
        for bucket in self.table:
            result.extend(bucket)  
        return result

    def keys(self):
        return [k for k, v in self.get_all()]

    def values(self):
        return [v for k, v in self.get_all()]          # 获取所有值



# 2. 二叉搜索树 (Binary Search Tree)
class BSTNode:
    def __init__(self, key, value):
        self.key = key          
        self.value = value      
        self.left = None        
        self.right = None                               #节点类

class BinarySearchTree:
    def __init__(self):
        self.root = None                                # 初始化根节点

    def insert(self, key, value):
        if self.root is None:
            self.root = BSTNode(key, value)    
        else:
            self._insert_recursive(self.root, key, value)       # 插入节点

    def _insert_recursive(self, node, key, value):
        if key < node.key:
            if node.left is None:
                node.left = BSTNode(key, value)  
            else:
                self._insert_recursive(node.left, key, value)  
        elif key > node.key:
            if node.right is None:
                node.right = BSTNode(key, value)
            else:
                self._insert_recursive(node.right, key, value)
        else:
            node.value = value                            # 递归插入节点值

    def search(self, key):
        return self._search_recursive(self.root, key)

    def _search_recursive(self, node, key):
        if node is None:
            return None   
        if key == node.key:
            return node.value   
        elif key < node.key:
            return self._search_recursive(node.left, key)   
        else:
            return self._search_recursive(node.right, key)      # 递归查找节点

    def search_range(self, min_key, max_key):
        result = []
        self._search_range_recursive(self.root, min_key, max_key, result)
        return result

    def _search_range_recursive(self, node, min_key, max_key, result):
        if node is None:
            return

        if node.key > min_key:
            self._search_range_recursive(node.left, min_key, max_key, result)

        if min_key <= node.key <= max_key:
            result.append(node.value)

        if node.key < max_key:
            self._search_range_recursive(node.right, min_key, max_key, result)      # 递归查找范围节点

    def inorder_traversal(self):
        result = []
        self._inorder(self.root, result)
        return result

    def _inorder(self, node, result):
        if node:
            self._inorder(node.left, result)   
            result.append(node.value)           
            self._inorder(node.right, result)           # 递归中序遍历

    def delete(self, key):
        self.root = self._delete_recursive(self.root, key)

    def _delete_recursive(self, node, key):
        if node is None:
            return None

        if key < node.key:
            node.left = self._delete_recursive(node.left, key)
        elif key > node.key:
            node.right = self._delete_recursive(node.right, key)
        else:
            if node.left is None:
                return node.right
            elif node.right is None:
                return node.left

            successor = self._find_min(node.right)
            node.key = successor.key
            node.value = successor.value
            node.right = self._delete_recursive(node.right, successor.key)

        return node                                        # 删除节点

    def _find_min(self, node):
        current = node
        while current.left is not None:
            current = current.left
        return current                                        # 查找最小节点

# 3. 优先队列 (Priority Queue)

class PriorityQueue:

    def __init__(self):
        self.heap = [None]  
        self.size = 0               # 初始化堆大小

    def _parent(self, index):
        return index // 2

    def _left_child(self, index):
        return index * 2

    def _right_child(self, index):
        return index * 2 + 1

    def _swap(self, i, j):
        self.heap[i], self.heap[j] = self.heap[j], self.heap[i]             # 交换节点

    def add(self, priority, value):
        self.heap.append((priority, value))
        self.size += 1

        current = self.size
        while current > 1:
            parent = self._parent(current)
            if self.heap[current][0] < self.heap[parent][0]:
                self._swap(current, parent)
                current = parent
            else:
                break             # 插入，上浮到正确位置，跳出循环

    def poll(self):
        if self.size == 0:
            return None

        result = self.heap[1]   

        self.heap[1] = self.heap[self.size]
        self.heap.pop()
        self.size -= 1

        current = 1
        while True:
            smallest = current
            left = self._left_child(current)
            right = self._right_child(current)

            if left <= self.size and self.heap[left][0] < self.heap[smallest][0]:
                smallest = left
            if right <= self.size and self.heap[right][0] < self.heap[smallest][0]:
                smallest = right

            if smallest != current:
                self._swap(current, smallest)
                current = smallest
            else:
                break

        return result                                        # 删除节点，返回优先级最高的节点

    def peek(self):
        if self.size == 0:
            return None
        return self.heap[1]                                        # 查看优先级最高的节点

    def is_empty(self):
        return self.size == 0                                        # 判断队列是否为空

    def get_all(self):
        return self.heap[1:]                                        # 获取所有节点

# 4. 队列 (Queue)

class QueueNode:
    def __init__(self, value):
        self.value = value    
        self.next = None                    # 初始化下一个节点为None


class Queue:

    def __init__(self):
        self.front = None   
        self.rear = None    
        self._count = 0                    # 初始化队列大小为0

    def enqueue(self, value):
        new_node = QueueNode(value)
        if self.rear is None:
            self.front = new_node
            self.rear = new_node
        else:
            self.rear.next = new_node
            self.rear = new_node
        self._count += 1                    # 入队

    def dequeue(self):
        if self.front is None:
            return None

        value = self.front.value     
        self.front = self.front.next  

        if self.front is None:
            self.rear = None  
        self._count -= 1                    
        return value                        # 出队                

    def peek(self):
        if self.front is None:
            return None
        return self.front.value                # 查看队头节点的值

    def is_empty(self):
        return self.front is None             # 判断队列是否为空

    def size(self):
        return self._count                    # 获取队列大小

    def get_all(self):
        result = []
        current = self.front
        while current:
            result.append(current.value)
            current = current.next
        return result                       # 获取所有节点

